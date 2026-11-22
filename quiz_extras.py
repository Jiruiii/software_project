"""Optional classroom features; uses the service's transaction and role checks."""
import csv
from datetime import datetime, timezone
import io
import json
import secrets
import time
import unicodedata
from difflib import SequenceMatcher
from functools import wraps


def expire_first(method):
    """Finish expiry in its own transaction before a request can fail/roll back."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            if not self.db.in_transaction: self.tick()
            return method(self, *args, **kwargs)
    return call


def csv_bytes(rows):
    def safe(value):
        value = str(value if value is not None else "")
        # Excel may strip leading whitespace before interpreting a formula.
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value
    output = io.StringIO(newline="")
    csv.writer(output).writerows([[safe(value) for value in row] for row in rows])
    return output.getvalue().encode("utf-8-sig")


class ExtraFeatures:
    def tick(self):
        with self.lock, self.db:
            due=list(self.db.execute("SELECT a.id,o.mode FROM activities a JOIN activity_options o ON a.id=o.activity_id WHERE a.phase='active' AND o.deadline IS NOT NULL AND o.deadline<=?", (time.time(),)))
            for row in due:
                if row['mode']=='sequential': self._close_round(row['id'])
                else:
                    self.db.execute("UPDATE activities SET phase='results',ended_at=(SELECT deadline FROM activity_options WHERE activity_id=?) WHERE id=?", (row['id'],row['id']))
                    self.db.execute('UPDATE activity_options SET deadline=NULL WHERE activity_id=?', (row['id'],))

    def _published_points(self, state, units, options):
        published = list(units)
        if state['phase'] != 'results':
            if state['phase'] != 'active' or options['mode'] != 'sequential': return {}
            published = published[:options['round_index'] + (0 if options['round_open'] else 1)]
        if not published: return {}
        by_question = {q:unit for unit in published for q in units[unit]}
        submissions = {unit:{} for unit in published}
        for row in self.db.execute('SELECT id,question_id,group_id,stake,verdict FROM answers WHERE activity_id=? ORDER BY id', (state['id'],)):
            unit = by_question.get(row['question_id'])
            if unit is not None: submissions[unit].setdefault(row['group_id'], []).append(row)
        points = {}
        for unit, groups in submissions.items():
            place = 0
            for group, rows in sorted(groups.items(),key=lambda item:item[1][-1]['id']):
                wager = self._unit_points(rows, units[unit])
                speed = 0
                if options['speed_scoring'] and len(rows)==len(units[unit]) and all(r['verdict']=='correct' for r in rows):
                    if place < 3: speed = (4,2,1)[place]
                    place += 1
                points.setdefault(group,{})[unit] = {'wager':wager,'speed':speed,'total':wager+speed}
        return points

    @staticmethod
    def _sum_points(points):
        return {key:sum(row[key] for row in points.values()) for key in ('wager','speed','total')}

    def _scoreboard(self, aid, points):
        scores = []
        for group in self.db.execute('SELECT id,name FROM groups WHERE activity_id=?', (aid,)):
            parts=self._sum_points(points.get(group['id'],{}))
            scores.append({'group_name':group['name'], 'score':parts['total'], 'wager':parts['wager'], 'speed':parts['speed']})
        return self._rank_scores(scores)

    @staticmethod
    def _rank_scores(scores):
        scores.sort(key=lambda row:(-row['score'],row['group_name'].casefold(),row['group_name']))
        last_score,rank=None,0
        for i,row in enumerate(scores,1):
            if row['score'] != last_score: rank=i
            last_score=row['score']; row['rank']=rank
        return scores

    @expire_first
    def submit_unit(self, token, aid, unit, answers, stake=0):
        from quiz_service import QuizError, text
        with self.lock, self.db:
            self._auth(token, "student", aid); self._activity(aid)
            if not isinstance(unit, str) or unit not in self._units(aid): raise QuizError(404, "題組不存在。")
            questions = self._units(aid)[unit]
            if not isinstance(answers, dict) or set(answers) != set(questions):
                raise QuizError(400, "請一次填齊此題組的所有子題，不能增加或缺少題號。")
            received = time.time()
            return {"answers":[self.submit(token, aid, q, answers[q], stake, _bundle=True, _commit=False, _received=received) for q in questions]}

    @staticmethod
    def _unit_points(answers, questions):
        if len(answers) != len(questions): return 0
        if any(a["verdict"] == "incorrect" for a in answers): return -answers[0]["stake"]
        if all(a["verdict"] == "correct" for a in answers): return answers[0]["stake"]
        return 0

    def _own_score(self, answers, units, total):
        lookup={a['question_id']:a for a in answers}
        pending, awaiting=0,0
        for qs in units.values():
            own=[lookup[q] for q in qs if q in lookup]
            if any(a['verdict']=='withheld' for a in own):
                awaiting += 1
                continue
            if own and not any(a['verdict']=='incorrect' for a in own) and any(a['verdict']=='pending' for a in own):
                pending += 1
        return {'total':total,'pending_units':pending,'awaiting_close_units':awaiting}

    @expire_first
    def reference(self, token, aid, question, answer, override=False):
        from quiz_service import QuizError
        with self.lock, self.db:
            self._auth(token, "teacher")
            activity = self._activity(aid)
            if not isinstance(answer, str) or len(answer) > 2000: raise QuizError(400, "參考答案最多 2000 字。")
            if not isinstance(question, str): raise QuizError(400, "請提供題號。")
            if not self.db.execute('SELECT 1 FROM questions WHERE activity_id=? AND id=?', (aid, question)).fetchone():
                raise QuizError(404, "題號不存在。")
            if not self._reviewable(activity, question): raise QuizError(409, "請先關閉此題或結束活動，再填寫老師答案。")
            if type(override) is not bool: raise QuizError(400, "請選擇是否用老師答案更新學習單。")
            if override and not answer.strip(): raise QuizError(400, "請先填寫老師答案，再勾選更新學習單。")
            if override and not self.db.execute('SELECT 1 FROM sheet_sources WHERE activity_id=?', (aid,)).fetchone():
                raise QuizError(409, "這是手動題號活動，只能儲存參考答案。")
            cursor = self.db.execute("UPDATE question_meta SET reference_answer=?,reference_override=? WHERE activity_id=? AND question_id=?", (answer.strip(), int(override), aid, question))
            if not cursor.rowcount: raise QuizError(404, "題號不存在。")
            self._invalidate_sheet_export(aid)
            return {"ok":True}

    def _report(self, state):
        answers = {a["question_id"]:a for a in state["answers"]}
        winners = {r["question_id"]:r["winner"] for r in state["results"]}
        rows = []
        for unit in state["units"]:
            qs = unit["questions"]
            parts = (answers.get(qs[0]) or {}).get('points',{'wager':0,'speed':0,'total':0})
            for index, q in enumerate(qs):
                answer = answers.get(q)
                rows.append({"question":q, "unit":unit["id"], "answer":answer["text"] if answer else "未作答",
                             "verdict":answer["verdict"] if answer else "unanswered", "stake":answer["stake"] if answer else None,
                             "points":parts['total'] if index == 0 else None,
                             "wager":parts['wager'] if index == 0 else None, "speed":parts['speed'] if index == 0 else None,
                             "successful":bool(winners[q] and winners[q]["group_name"] == state["group_name"]),
                             "reference":state["references"][q]})
        return rows

    def report_csv(self, token, aid):
        from quiz_service import QuizError
        with self.lock:
            self._auth(token, "student", aid)
            state = self.snapshot(token, aid)
            if state["phase"] != "results": raise QuizError(409, "請等活動結束再查看報告。")
            names = {"pending":"未判定", "correct":"正確", "incorrect":"錯誤", "unanswered":"未作答"}
            rows = [["活動", "組別", "題號", "題組", "本組答案", "判定", "下注", "單位得分（每題組只列一次）", "搶答成功", "參考答案"]]
            rows.extend([[state["title"], state["group_name"], r["question"], r["unit"], r["answer"], names[r["verdict"]], r["stake"], r["points"], "是" if r["successful"] else "否", r["reference"]] for r in state["report"]])
            rows[0].append('成績狀態')
            for row in rows[1:]: row.append('批改完成' if state['grading']['complete'] else '暫時成績')
            rows[0].extend(['押注分','搶答分'])
            for row, detail in zip(rows[1:],state['report']): row.extend([detail['wager'],detail['speed']])
            return csv_bytes(rows)

    def clusters(self, token, aid, question):
        from quiz_service import QuizError
        with self.lock:
            self._auth(token, "teacher")
            state = self.snapshot(token, aid)
            if question not in state["questions"]: raise QuizError(404, "題號不存在。")
            answers = [a for a in state["answers"] if a["question_id"] == question]
        # Copy under the lock, compare outside it so submissions never wait on
        # quadratic string matching. Beyond 200 representatives use exact only.
        clusters, exact, limited = [], {}, False
        for answer in answers:
            normalized = " ".join(unicodedata.normalize("NFKC", answer["text"]).casefold().split())
            index = exact.get(normalized)
            if index is None and len(clusters) < 200:
                index = next((i for i, c in enumerate(clusters) if SequenceMatcher(None, normalized, c["normalized"]).ratio() >= .85), None)
            elif index is None:
                limited = True
            if index is None:
                index = len(clusters); clusters.append({"normalized":normalized, "answers":[]})
            exact[normalized] = index
            clusters[index]["answers"].append({k:answer[k] for k in ("id", "group_name", "text", "verdict", "review_revision")})
        for cluster in clusters:
            cluster["exact"] = len({a["text"] for a in cluster["answers"]}) == 1
        return {"clusters":clusters, "threshold":.85, "limited":limited,
                "reviewable":question in state["reviewable_questions"]}

    def _init_extras(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS review_batches (
                id TEXT PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES activities(id),
                owner TEXT NOT NULL, changes_json TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS activity_options (
                activity_id TEXT PRIMARY KEY REFERENCES activities(id),
                mode TEXT NOT NULL DEFAULT 'all', fairness INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                round_index INTEGER NOT NULL DEFAULT -1, round_open INTEGER NOT NULL DEFAULT 0,
                round_started_at REAL, deadline REAL, priority_until REAL NOT NULL DEFAULT 0,
                eligible_json TEXT NOT NULL DEFAULT '[]', participants_json TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS question_meta (
                activity_id TEXT, question_id TEXT, unit_id TEXT NOT NULL,
                reference_answer TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(activity_id,question_id),
                FOREIGN KEY(activity_id,question_id) REFERENCES questions(activity_id,id));
            INSERT OR IGNORE INTO activity_options(activity_id) SELECT id FROM activities;
            INSERT OR IGNORE INTO question_meta(activity_id,question_id,unit_id)
                SELECT activity_id,id,id FROM questions;
        """)
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(answers)")}
        option_columns = {r['name'] for r in self.db.execute('PRAGMA table_info(activity_options)')}
        if 'priority_source' not in option_columns:
            self.db.execute('ALTER TABLE activity_options ADD COLUMN priority_source TEXT REFERENCES activities(id)')
        if 'speed_scoring' not in option_columns:
            self.db.execute('ALTER TABLE activity_options ADD COLUMN speed_scoring INTEGER NOT NULL DEFAULT 1')
            self.db.execute("UPDATE activity_options SET speed_scoring=0 WHERE activity_id IN (SELECT id FROM activities WHERE phase!='preparing')")
        if "stake" not in columns:
            self.db.execute("ALTER TABLE answers ADD COLUMN stake INTEGER NOT NULL DEFAULT 1")
        if "verdict" not in columns:
            self.db.execute("ALTER TABLE answers ADD COLUMN verdict TEXT NOT NULL DEFAULT 'pending'")
        if "review_revision" not in columns:
            self.db.execute("ALTER TABLE answers ADD COLUMN review_revision INTEGER NOT NULL DEFAULT 0")
        if "elapsed_basis" not in columns:
            self.db.execute("ALTER TABLE answers ADD COLUMN elapsed_basis TEXT NOT NULL DEFAULT 'activity'")
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(question_meta)')}
        for name, definition in [('question_type', "TEXT NOT NULL DEFAULT 'short'"),
                                 ('prompt', "TEXT NOT NULL DEFAULT ''"),
                                 ('options_json', "TEXT NOT NULL DEFAULT '[]'"),
                                 ('correct_index', 'INTEGER'),
                                 ('correct_indices', "TEXT NOT NULL DEFAULT '[]'"),
                                 ('betting_enabled', 'INTEGER NOT NULL DEFAULT 1'), ('opened_at', 'REAL'),
                                 ('reference_override', 'INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:
                self.db.execute(f'ALTER TABLE question_meta ADD COLUMN {name} {definition}')
        self._migrate_answer_timing()
        self.db.commit()

    def _migrate_answer_timing(self):
        # Older versions retained only the last sequential round's opening.
        for activity in self.db.execute("SELECT a.id,a.started_at,o.mode,o.round_index,o.round_started_at FROM activities a JOIN activity_options o ON a.id=o.activity_id WHERE a.started_at IS NOT NULL").fetchall():
            if activity['mode'] == 'all':
                self.db.execute('UPDATE question_meta SET opened_at=? WHERE activity_id=? AND opened_at IS NULL',
                                (activity['started_at'], activity['id']))
            elif activity['round_index'] >= 0 and activity['round_started_at'] is not None:
                units = list(self._units(activity['id']).values())
                if activity['round_index'] < len(units):
                    self.db.executemany('UPDATE question_meta SET opened_at=? WHERE activity_id=? AND question_id=? AND opened_at IS NULL',
                                        [(activity['round_started_at'], activity['id'], q) for q in units[activity['round_index']]])
        old = self.db.execute("SELECT a.id,a.received_at,m.opened_at FROM answers a JOIN question_meta m ON m.activity_id=a.activity_id AND m.question_id=a.question_id WHERE a.elapsed_basis='activity' AND m.opened_at IS NOT NULL").fetchall()
        self.db.executemany("UPDATE answers SET elapsed_ms=?,elapsed_basis='question' WHERE id=?",
                            [(max(0, round((r['received_at']-r['opened_at'])*1000)), r['id']) for r in old])

    def question_settings(self, token, aid, unit, betting_enabled, questions):
        from quiz_service import QuizError, text
        with self.lock, self.db:
            self._auth(token, 'teacher')
            if self._activity(aid)['phase'] != 'preparing':
                raise QuizError(409, '活動開始後不能修改題型、正解或下注開關。')
            units = self._units(aid)
            if not isinstance(unit, str) or unit not in units: raise QuizError(404, '題組不存在。')
            if type(betting_enabled) is not bool: raise QuizError(400, '請提供下注開關。')
            if not isinstance(questions, list) or len(questions) != len(units[unit]):
                raise QuizError(400, '請提供該單位全部子題設定。')
            clean = {}
            for item in questions:
                if not isinstance(item, dict) or not isinstance(item.get('question'), str):
                    raise QuizError(400, '題目設定格式不正確。')
                q, kind = item['question'], item.get('type')
                if q not in units[unit] or q in clean or kind not in ('short', 'choice', 'multiple'):
                    raise QuizError(400, '題號重複、不屬於此題組或題型無效。')
                options, correct, indices = [], None, []
                if kind != 'short':
                    options = item.get('options')
                    if not isinstance(options, list) or not 2 <= len(options) <= 8:
                        raise QuizError(400, '選擇題需要 2～8 個選項。')
                    options = [text(option, '選項', 200) for option in options]
                    if len(set(options)) != len(options): raise QuizError(400, '選項不能重複。')
                    if kind == 'multiple':
                        indices = item.get('correct_indices')
                        if any(len(option.splitlines()) != 1 for option in options):
                            raise QuizError(400, '多選題的每個選項只能有一行。')
                        if not isinstance(indices, list) or not 1 <= len(indices) <= len(options) or any(type(i) is not int or not 0 <= i < len(options) for i in indices) or len(set(indices)) != len(indices):
                            raise QuizError(400, '請指定至少一個不重複的有效正解。')
                    else:
                        correct = item.get('correct_index')
                        if type(correct) is not int or not 0 <= correct < len(options):
                            raise QuizError(400, '請指定一個有效的正確選項。')
                prompt = item.get('prompt')
                if 'prompt' in item and not isinstance(prompt, str):
                    raise QuizError(400, '題目內容必須是文字。')
                clean[q] = (kind, json.dumps(options, ensure_ascii=False), correct, json.dumps(indices), int(betting_enabled), prompt.strip() if prompt is not None else None, aid, q)
            self.db.executemany('UPDATE question_meta SET question_type=?,options_json=?,correct_index=?,correct_indices=?,betting_enabled=?,prompt=COALESCE(?,prompt) WHERE activity_id=? AND question_id=?', clean.values())
            return {'ok': True}

    def _grade_submission(self, aid, question, answer, stake):
        from quiz_service import QuizError, text
        config=self.db.execute('SELECT * FROM question_meta WHERE activity_id=? AND question_id=?',(aid,question)).fetchone()
        if not config: raise QuizError(404, '題號不存在。')
        if not config['betting_enabled'] and stake != 0:
            raise QuizError(400, '這題未開放下注，請選擇不押。')
        options=json.loads(config['options_json'])
        if config['question_type'] == 'multiple':
            if not isinstance(answer, list) or not 1 <= len(answer) <= len(options) or any(item not in options for item in answer) or len(set(answer)) != len(answer):
                raise QuizError(400, '請至少勾選一項，且只能送出不重複的有效選項。')
            selected = [i for i, option in enumerate(options) if option in answer]
            verdict = 'correct' if selected == sorted(json.loads(config['correct_indices'])) else 'incorrect'
            return '\n'.join(options[i] for i in selected), verdict
        answer = text(answer, '答案', 2000)
        if config['question_type'] == 'short': return answer, 'pending'
        if answer not in options: raise QuizError(400, '請選擇題目提供的有效選項。')
        return answer, 'correct' if answer == options[config['correct_index']] else 'incorrect'

    def _winner_rows(self, aid):
        """Earliest complete unit not disqualified; one group wins every child."""
        rows = [dict(r) for r in self.db.execute("SELECT a.*,g.name AS group_name FROM answers a JOIN groups g ON g.id=a.group_id WHERE a.activity_id=? ORDER BY a.id", (aid,))]
        winners = {}
        for questions in self._units(aid).values():
            candidates = {}
            for row in rows:
                if row["question_id"] in questions:
                    candidates.setdefault(row["group_id"], []).append(row)
            for answers in candidates.values():
                if len(answers) == len(questions) and all(a["verdict"] != "incorrect" for a in answers):
                    winners.update({a["question_id"]: a for a in answers})
                    break
        return winners

    def _reviewable(self, activity, question):
        if activity["phase"] == "results": return True
        options = self._options(activity["id"])
        if activity["phase"] != "active" or options["mode"] != "sequential": return False
        units = list(self._units(activity["id"]).values())
        return any(question in qs and (i < options["round_index"] or (i == options["round_index"] and not options["round_open"])) for i, qs in enumerate(units))

    @expire_first
    def review(self, token, aid, answer_id, verdict, revision=None):
        from quiz_service import QuizError
        with self.lock, self.db:
            self._auth(token, "teacher")
            activity = self._activity(aid)
            if type(answer_id) is not int or verdict not in ("correct", "incorrect"):
                raise QuizError(400, "請提供有效答案與判定。")
            answer = self.db.execute("SELECT * FROM answers WHERE activity_id=? AND id=?", (aid, answer_id)).fetchone()
            if not answer: raise QuizError(404, "找不到這筆答案。")
            if self.courses and (type(revision) is not int or revision != answer['review_revision']):
                raise QuizError(409, '批改版本已變更，請重新查看後再判定。')
            if not self._reviewable(activity, answer["question_id"]):
                raise QuizError(409, "請先關閉此題或結束活動，再判定答案。")
            self.db.execute("UPDATE answers SET verdict=?,review_revision=review_revision+1 WHERE id=?", (verdict, answer_id))
            self._log_grades(token, [answer_id])
            self._invalidate_sheet_export(aid)
            return {"ok": True}

    def _log_grades(self, token, ids):
        if self.courses:
            uid = self.courses.scope(token)['uid']
            self.db.executemany('INSERT INTO grade_log SELECT id,review_revision,?,verdict,? FROM answers WHERE id=?',
                                [(uid, time.time(), answer_id) for answer_id in ids])

    def _invalidate_sheet_export(self, aid):
        row = self.db.execute('SELECT source_json FROM sheet_sources WHERE activity_id=?', (aid,)).fetchone()
        if not row: return
        source = json.loads(row['source_json'])
        activity = self._activity(aid)
        winners = self._sheet_answers(activity)
        last = source.get('last_export', {})
        desired = {t['question']:(winners[t['question']] if t['question'] in winners else t['original'])
                   for t in source['targets'] if self._reviewable(activity,t['question']) and (t['question'] in winners or t['question'] in last)}
        if desired != last:
            self.db.execute('UPDATE sheet_sources SET exported_at=NULL WHERE activity_id=?', (aid,))
            if aid in self.sheet_sync_states:
                self.sheet_sync_states[aid] = {'state':'queued', 'message':'答案已更新，等待同步學習單。'}

    def _sheet_answers(self, activity):
        aid = activity['id']
        answers = {q:f"{a['text']}（{a['group_name']}）" for q,a in self._winner_rows(aid).items() if self._reviewable(activity,q)}
        for row in self.db.execute('SELECT question_id,reference_answer FROM question_meta WHERE activity_id=? AND reference_override=1', (aid,)):
            if row['reference_answer'] and self._reviewable(activity,row['question_id']):
                answers[row['question_id']] = f"{row['reference_answer']}（老師答案）"
        return answers

    @expire_first
    def review_batch(self, token, aid, question, selections, verdict):
        from quiz_service import QuizError
        with self.lock, self.db:
            owner = self._auth(token, "teacher")["token_hash"]
            activity = self._activity(aid)
            if not isinstance(question, str) or verdict not in ("correct", "incorrect"):
                raise QuizError(400, "請提供有效題號與判定。")
            if not isinstance(selections, list) or not 1 <= len(selections) <= 1000:
                raise QuizError(400, "請勾選 1～1000 筆答案。")
            if any(not isinstance(s, dict) or type(s.get("id")) is not int or
                   type(s.get("revision")) is not int or s["revision"] < 0 for s in selections):
                raise QuizError(400, "答案清單格式錯誤，請重新比較。")
            if len({s["id"] for s in selections}) != len(selections):
                raise QuizError(400, "答案清單不能重複。")
            if not self._reviewable(activity, question):
                raise QuizError(409, "請先關閉此題或結束活動，再判定答案。")
            changes = []
            for selection in selections:
                answer = self.db.execute("SELECT * FROM answers WHERE activity_id=? AND question_id=? AND id=?",
                                         (aid, question, selection["id"])).fetchone()
                if not answer: raise QuizError(404, "答案不屬於此活動與題目。")
                if answer["review_revision"] != selection["revision"]:
                    raise QuizError(409, "部分答案已被批改；本次未變更任何答案，請重新比較。")
                changes.append({"id":answer["id"], "before":answer["verdict"],
                                "revision":answer["review_revision"] + 1})
            self.db.executemany("UPDATE answers SET verdict=?,review_revision=? WHERE id=?",
                                [(verdict, c["revision"], c["id"]) for c in changes])
            batch_id = secrets.token_hex(16)
            self._log_grades(token, [c['id'] for c in changes])
            self.db.execute("INSERT INTO review_batches(id,activity_id,owner,changes_json) VALUES(?,?,?,?)",
                            (batch_id, aid, owner, json.dumps(changes)))
            self._invalidate_sheet_export(aid)
            return {"batch_id":batch_id, "count":len(changes)}

    @expire_first
    def undo_review_batch(self, token, aid, batch_id):
        from quiz_service import QuizError
        with self.lock, self.db:
            owner = self._auth(token, "teacher")["token_hash"]
            activity = self._activity(aid)
            if not isinstance(batch_id, str): raise QuizError(400, "請提供批改紀錄。")
            batch = self.db.execute("SELECT * FROM review_batches WHERE id=? AND activity_id=? AND owner=?",
                                    (batch_id, aid, owner)).fetchone()
            if not batch: raise QuizError(404, "找不到可撤銷的批改紀錄。")
            if batch["undone"]: raise QuizError(409, "此批次已撤銷。")
            changes = json.loads(batch["changes_json"])
            for change in changes:
                answer = self.db.execute("SELECT * FROM answers WHERE activity_id=? AND id=?", (aid, change["id"])).fetchone()
                if not answer or answer["review_revision"] != change["revision"]:
                    raise QuizError(409, "部分答案已有後續批改，無法撤銷；本次未變更任何答案。")
                if not self._reviewable(activity, answer["question_id"]):
                    raise QuizError(409, "此題目前不能批改。")
            self.db.executemany("UPDATE answers SET verdict=?,review_revision=review_revision+1 WHERE id=?",
                                [(c["before"], c["id"]) for c in changes])
            self.db.execute("UPDATE review_batches SET undone=1 WHERE id=?", (batch_id,))
            self._log_grades(token, [c['id'] for c in changes])
            self._invalidate_sheet_export(aid)
            return {"ok":True, "count":len(changes)}

    def _new_options(self, aid):
        self.db.execute("INSERT INTO activity_options(activity_id) VALUES(?)", (aid,))
        self.db.execute("INSERT INTO question_meta(activity_id,question_id,unit_id) SELECT activity_id,id,id FROM questions WHERE activity_id=?", (aid,))

    def _options(self, aid):
        return dict(self.db.execute("SELECT * FROM activity_options WHERE activity_id=?", (aid,)).fetchone())

    def _units(self, aid):
        units = {}
        for row in self.db.execute("SELECT q.id,m.unit_id FROM questions q JOIN question_meta m ON m.activity_id=q.activity_id AND m.question_id=q.id WHERE q.activity_id=? ORDER BY q.ordinal", (aid,)):
            units.setdefault(row["unit_id"], []).append(row["id"])
        return units

    def configure(self, token, aid, mode, fairness=False, duration_seconds=0, priority_source=None):
        from quiz_service import QuizError
        with self.lock, self.db:
            self._auth(token, "teacher", aid)
            if self.courses and self.courses.scope(token)["kind"] != "owner":
                raise QuizError(403, "只有授課老師可修改活動規則。")
            if self._activity(aid)["phase"] != "preparing":
                raise QuizError(409, "活動開始後不能修改規則。")
            if mode not in ("all", "sequential") or type(fairness) is not bool:
                raise QuizError(400, "請選擇有效的搶答模式與保底開關。")
            if fairness and mode != "sequential":
                raise QuizError(400, "保底只適用逐題模式。")
            if type(duration_seconds) is not int or not 0 <= duration_seconds <= 3600:
                raise QuizError(400, "倒數必須是 0～3600 的整數秒；0 表示不限時。")
            if priority_source is not None:
                if mode != "all" or not self.courses or not isinstance(priority_source, str) or not priority_source:
                    raise QuizError(400, "請在課程全題模式選擇有效的保底來源場次。")
                self.courses.check_priority_source(token, priority_source)
            self.db.execute(
                "UPDATE activity_options SET mode=?,fairness=?,duration_seconds=?,priority_source=? WHERE activity_id=?",
                (mode, int(fairness), duration_seconds, priority_source, aid),
            )
            return {"ok": True}

    def _open_round(self, aid, index):
        options = self._options(aid)
        participants = [r["id"] for r in self.db.execute("SELECT id FROM groups WHERE activity_id=?", (aid,))]
        units = self._units(aid)
        eligible = []
        if options["fairness"] and participants:
            points = self._published_points(self._activity(aid), units, options)
            totals = {gid:self._sum_points(points.get(gid, {}))["total"] for gid in participants}
            minimum = min(totals.values())
            eligible = [gid for gid in participants if totals[gid] == minimum]
        now = time.time()
        questions = list(units.values())[index]
        self.db.executemany('UPDATE question_meta SET opened_at=? WHERE activity_id=? AND question_id=?',
                            [(now, aid, q) for q in questions])
        self.db.execute("UPDATE activity_options SET round_index=?,round_open=1,round_started_at=?,priority_until=?,eligible_json=?,participants_json=? WHERE activity_id=?",
                        (index, now, now+3 if eligible else 0, json.dumps(eligible), json.dumps(participants), aid))
        self.db.execute('UPDATE activity_options SET deadline=? WHERE activity_id=?', (now+options['duration_seconds'] if options['duration_seconds'] else None,aid))

    def _close_round(self, aid):
        options = self._options(aid)
        if not options["round_open"]:
            return
        units = list(self._units(aid).values())
        self.db.execute("UPDATE activity_options SET round_open=0,deadline=NULL WHERE activity_id=?", (aid,))
        if options["round_index"] == len(units)-1:
            self.db.execute("UPDATE activities SET phase='results',ended_at=? WHERE id=?", (time.time(), aid))


    @expire_first
    def round_action(self, token, aid, action):
        from quiz_service import QuizError
        with self.lock, self.db:
            self._auth(token, "teacher")
            activity, options = self._activity(aid), self._options(aid)
            if activity["phase"] != "active" or options["mode"] != "sequential":
                raise QuizError(409, "目前不是逐題搶答階段。")
            if action == "close":
                self._close_round(aid)
            elif action == "next" and not options["round_open"] and options["round_index"]+1 < len(self._units(aid)):
                self._open_round(aid, options["round_index"]+1)
            else:
                raise QuizError(409, "請先關閉當題，再開下一題。")
            return {"ok": True}

    def _submission_gate(self, activity, session, question, received=None):
        from quiz_service import QuizError
        options = self._options(activity["id"])
        now = time.time() if received is None else received
        if options['deadline'] is not None and now >= options['deadline']:
            raise QuizError(409, "作答時間已到，答案未送出。")
        if options["mode"] == "sequential":
            units = list(self._units(activity["id"]).values())
            if not options["round_open"] or options["round_index"] < 0 or question not in units[options["round_index"]]:
                raise QuizError(409, "這一題尚未開放或已關閉。")
        if now < options["priority_until"] and session["group_id"] not in json.loads(options["eligible_json"]):
            raise QuizError(409, "目前是保底先答時間，請等待倒數結束。")

    def _extra_snapshot(self, state, session):
        state['question_settings'] = {}
        for row in self.db.execute('SELECT * FROM question_meta WHERE activity_id=?', (state['id'],)):
            config={'type':row['question_type'], 'options':json.loads(row['options_json']), 'betting_enabled':bool(row['betting_enabled'])}
            if session['role'] == 'teacher': config['correct_index'] = row['correct_index']
            if session['role'] == 'teacher' and row['question_type'] == 'multiple':
                config['correct_indices'] = json.loads(row['correct_indices'])
            if session['role'] == 'teacher' or row['opened_at'] is not None:
                config['prompt'] = row['prompt']
            state['question_settings'][row['question_id']] = config
        options = self._options(state["id"])
        units = self._units(state["id"])
        state["units"] = [{"id": u, "questions": qs} for u, qs in units.items()]
        points = self._published_points(state,units,options)
        first = {qs[0]:unit for unit,qs in units.items()}
        for answer in state['answers']:
            detail = points.get(answer.get('group_id',session['group_id']),{}).get(first.get(answer['question_id']))
            if detail is not None: answer['points'] = detail
        state['speed_scoring'] = bool(options['speed_scoring'])
        if session['role'] == 'student':
            state['own_points'] = self._sum_points(points.get(session['group_id'],{}))
            state['own_score'] = self._own_score(state['answers'],units,state['own_points']['total'])
            state['chat_available'] = state['phase'] == 'active' and self.chat_student(session)
        if state['phase'] == 'active':
            state['top_five'] = [
                {key: row[key] for key in ('rank', 'group_name', 'score')}
                for row in self._scoreboard(state['id'], points)[:5]
            ]
        state["settings"] = {k: options[k] for k in ("mode", "fairness", "duration_seconds")}
        state["server_time"] = time.time()
        state["round"] = {k: options[k] for k in ("round_index", "round_open", "round_started_at", "priority_until", "deadline")}
        state["round"]["unit_id"] = list(units)[options["round_index"]] if options["round_index"] >= 0 else None
        state["round"]["own_priority"] = session["group_id"] in json.loads(options["eligible_json"])
        available = state["questions"] if state["phase"] == "active" else []
        if options["mode"] == "sequential":
            available = units.get(state["round"]["unit_id"], []) if options["round_open"] and state["phase"] == "active" else []
        if state["server_time"] < options["priority_until"] and not state["round"]["own_priority"] and session["role"] == "student":
            available = []
        state["available_questions"] = available
        if session["role"] == "teacher":
            state["reviewable_questions"] = [q for q in state["questions"] if self._reviewable(state, q)]
            state['reference_overrides'] = {r['question_id']:bool(r['reference_override']) for r in self.db.execute('SELECT question_id,reference_override FROM question_meta WHERE activity_id=?', (state['id'],))}
        state["references"] = {r["question_id"]:r["reference_answer"]
                               for r in self.db.execute("SELECT question_id,reference_answer FROM question_meta WHERE activity_id=?", (state["id"],))
                               if session['role'] == 'teacher' or self._reviewable(state,r['question_id'])}
        if state["phase"] == "results":
            pending=self.db.execute("SELECT COUNT(*) FROM answers WHERE activity_id=? AND verdict='pending'",(state['id'],)).fetchone()[0]
            state['grading']={'pending_answers':pending,'complete':pending==0}
            state["scoreboard"] = self._scoreboard(state['id'],points)
            if session["role"] == "student": state["report"] = self._report(state)
        return state

    def activity_csv(self, token, aid):
        from quiz_service import QuizError
        with self.lock:
            self._auth(token, "teacher")
            state = self.snapshot(token, aid)
            if state["phase"] != "results":
                raise QuizError(409, "請先結束活動再下載紀錄。")
            winners = {r["question_id"]: r["winner"] for r in state["results"]}
            unit_ids = {q:u["id"] for u in state["units"] for q in u["questions"]}
            rows = [["題號", "題組", "組別", "答案", "收件時間 UTC", "計時基準", "送出秒數", "原始順位", "搶答成功"]]
            for question in state["questions"]:
                answers = [a for a in state["answers"] if a["question_id"] == question]
                if not answers:
                    rows.append([question, unit_ids[question], "", "無人作答", "", "", "", "", "否"])
                for rank, answer in enumerate(answers, 1):
                    winner = winners[question]
                    rows.append([question, unit_ids[question], answer["group_name"], answer["text"],
                                 datetime.fromtimestamp(answer["received_at"], timezone.utc).isoformat(),
                                 "該題開放" if answer['elapsed_basis'] == 'question' else "活動開始（舊紀錄）",
                                 f"{answer['elapsed_ms']/1000:.3f}", rank,
                                 "是" if winner and winner["group_name"] == answer["group_name"] else "否"])
            details={(a['question_id'],a['group_name']):a.get('points') for a in state['answers']}
            rows[0].extend(['押注分','搶答分','單位合計'])
            for row in rows[1:]:
                parts = details.get((row[0],row[2])) or {}
                row.extend(parts.get(key) for key in ('wager','speed','total'))
            return csv_bytes(rows)
