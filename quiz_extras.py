"""Optional classroom features; uses the service's transaction and role checks."""
import csv
from datetime import datetime, timezone
import io
import json
import time


def csv_bytes(rows):
    def safe(value):
        value = str(value if value is not None else "")
        # Excel may strip leading whitespace before interpreting a formula.
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value
    output = io.StringIO(newline="")
    csv.writer(output).writerows([[safe(value) for value in row] for row in rows])
    return output.getvalue().encode("utf-8-sig")


class ExtraFeatures:
    def _init_extras(self):
        self.db.executescript("""
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
            CREATE TABLE IF NOT EXISTS group_progress (
                group_id TEXT PRIMARY KEY REFERENCES groups(id), misses INTEGER NOT NULL DEFAULT 0);
            INSERT OR IGNORE INTO activity_options(activity_id) SELECT id FROM activities;
            INSERT OR IGNORE INTO question_meta(activity_id,question_id,unit_id)
                SELECT activity_id,id,id FROM questions;
        """)
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(answers)")}
        if "stake" not in columns:
            self.db.execute("ALTER TABLE answers ADD COLUMN stake INTEGER NOT NULL DEFAULT 1")
        if "verdict" not in columns:
            self.db.execute("ALTER TABLE answers ADD COLUMN verdict TEXT NOT NULL DEFAULT 'pending'")
        self.db.commit()

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

    def review(self, token, aid, answer_id, verdict):
        from quiz_service import QuizError
        with self.lock, self.db:
            self._auth(token, "teacher")
            activity = self._activity(aid)
            if type(answer_id) is not int or verdict not in ("pending", "correct", "incorrect"):
                raise QuizError(400, "請提供有效答案與判定。")
            answer = self.db.execute("SELECT * FROM answers WHERE activity_id=? AND id=?", (aid, answer_id)).fetchone()
            if not answer: raise QuizError(404, "找不到這筆答案。")
            if not self._reviewable(activity, answer["question_id"]):
                raise QuizError(409, "請先關閉此題或結束活動，再判定答案。")
            if answer["verdict"] != verdict:
                self.db.execute("UPDATE answers SET verdict=? WHERE id=?", (verdict, answer_id))
                self.db.execute("UPDATE sheet_sources SET exported_at=NULL WHERE activity_id=?", (aid,))
            return {"ok": True}

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

    def configure(self, token, aid, mode, fairness=False):
        from quiz_service import QuizError
        with self.lock, self.db:
            self._auth(token, "teacher")
            if self._activity(aid)["phase"] != "preparing":
                raise QuizError(409, "活動開始後不能修改規則。")
            if mode not in ("all", "sequential") or type(fairness) is not bool:
                raise QuizError(400, "請選擇有效的搶答模式與保底開關。")
            if fairness and mode != "sequential":
                raise QuizError(400, "保底只適用逐題模式。")
            self.db.execute("UPDATE activity_options SET mode=?,fairness=? WHERE activity_id=?", (mode, int(fairness), aid))
            return {"ok": True}

    def _open_round(self, aid, index):
        options = self._options(aid)
        participants = [r["id"] for r in self.db.execute("SELECT id FROM groups WHERE activity_id=?", (aid,))]
        eligible = []
        if options["fairness"]:
            for gid in participants:
                row = self.db.execute("SELECT misses FROM group_progress WHERE group_id=?", (gid,)).fetchone()
                if row and row["misses"] >= 3:
                    eligible.append(gid)
                    self.db.execute("UPDATE group_progress SET misses=0 WHERE group_id=?", (gid,))
        now = time.time()
        self.db.execute("UPDATE activity_options SET round_index=?,round_open=1,round_started_at=?,priority_until=?,eligible_json=?,participants_json=? WHERE activity_id=?",
                        (index, now, now+3 if eligible else 0, json.dumps(eligible), json.dumps(participants), aid))

    def _close_round(self, aid):
        options = self._options(aid)
        if not options["round_open"]:
            return
        units = list(self._units(aid).values())
        questions = units[options["round_index"]]
        first = self._winner_rows(aid).get(questions[0])
        winner = first["group_id"] if first else None
        for gid in json.loads(options["participants_json"]):
            self.db.execute("INSERT OR IGNORE INTO group_progress(group_id) VALUES(?)", (gid,))
            self.db.execute("UPDATE group_progress SET misses=CASE WHEN ? THEN 0 ELSE misses+1 END WHERE group_id=?", (gid == winner, gid))
        self.db.execute("UPDATE activity_options SET round_open=0 WHERE activity_id=?", (aid,))
        if options["round_index"] == len(units)-1:
            self.db.execute("UPDATE activities SET phase='results',ended_at=? WHERE id=?", (time.time(), aid))

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

    def _submission_gate(self, activity, session, question):
        from quiz_service import QuizError
        options = self._options(activity["id"])
        if options["mode"] != "sequential":
            return
        units = list(self._units(activity["id"]).values())
        if not options["round_open"] or options["round_index"] < 0 or question not in units[options["round_index"]]:
            raise QuizError(409, "這一題尚未開放或已關閉。")
        if time.time() < options["priority_until"] and session["group_id"] not in json.loads(options["eligible_json"]):
            raise QuizError(409, "目前是保底先答時間，請等待倒數結束。")

    def _extra_snapshot(self, state, session):
        options = self._options(state["id"])
        units = self._units(state["id"])
        state["units"] = [{"id": u, "questions": qs} for u, qs in units.items()]
        state["settings"] = {k: options[k] for k in ("mode", "fairness", "duration_seconds")}
        state["server_time"] = time.time()
        state["round"] = {k: options[k] for k in ("round_index", "round_open", "round_started_at", "priority_until", "deadline")}
        state["round"]["unit_id"] = list(units)[options["round_index"]] if options["round_index"] >= 0 else None
        state["round"]["own_priority"] = session["group_id"] in json.loads(options["eligible_json"])
        available = state["questions"] if state["phase"] == "active" else []
        if options["mode"] == "sequential":
            available = units.get(state["round"]["unit_id"], []) if options["round_open"] and state["phase"] == "active" else []
            if time.time() < options["priority_until"] and not state["round"]["own_priority"] and session["role"] == "student":
                available = []
        state["available_questions"] = available
        if session["role"] == "teacher":
            state["reviewable_questions"] = [q for q in state["questions"] if self._reviewable(state, q)]
        return state

    def activity_csv(self, token, aid):
        from quiz_service import QuizError
        with self.lock:
            self._auth(token, "teacher")
            state = self.snapshot(token, aid)
            if state["phase"] != "results":
                raise QuizError(409, "請先結束活動再下載紀錄。")
            winners = {r["question_id"]: r["winner"] for r in state["results"]}
            rows = [["題號", "題組", "組別", "答案", "收件時間 UTC", "開始後秒數", "原始順位", "搶答成功"]]
            for question in state["questions"]:
                answers = [a for a in state["answers"] if a["question_id"] == question]
                if not answers:
                    rows.append([question, question, "", "無人作答", "", "", "", "否"])
                for rank, answer in enumerate(answers, 1):
                    winner = winners[question]
                    rows.append([question, question, answer["group_name"], answer["text"],
                                 datetime.fromtimestamp(answer["received_at"], timezone.utc).isoformat(),
                                 f"{answer['elapsed_ms']/1000:.3f}", rank,
                                 "是" if winner and winner["group_name"] == answer["group_name"] else "否"])
            return csv_bytes(rows)
