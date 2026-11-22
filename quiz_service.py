"""Classroom domain service. Every decision is made on the server. [F-01..15]"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from quiz_extras import ExtraFeatures, expire_first


class QuizError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise QuizError(400, f"{name}必須是 1～{limit} 字的文字。")
    return value.strip()


class QuizService(ExtraFeatures):
    def __init__(self, database, teacher_password):
        if not teacher_password:
            raise ValueError("教師密碼不可空白")
        self.password_hash = hashlib.sha256(teacher_password.encode()).digest()
        self.lock = threading.RLock()
        self.courses = None
        self.login_attempts = {}
        self.sheet_sync_states = {}
        if str(database) != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS activities (
                id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                phase TEXT NOT NULL DEFAULT 'preparing', created_at REAL NOT NULL,
                started_at REAL, ended_at REAL);
            CREATE TABLE IF NOT EXISTS questions (
                activity_id TEXT REFERENCES activities(id), id TEXT, ordinal INTEGER,
                PRIMARY KEY(activity_id, id));
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY, activity_id TEXT REFERENCES activities(id),
                name TEXT NOT NULL, normalized_name TEXT NOT NULL,
                UNIQUE(activity_id, normalized_name));
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, role TEXT NOT NULL,
                activity_id TEXT REFERENCES activities(id), group_id TEXT REFERENCES groups(id),
                expires_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT, question_id TEXT,
                group_id TEXT REFERENCES groups(id), text TEXT NOT NULL,
                received_at REAL NOT NULL, elapsed_ms INTEGER NOT NULL,
                FOREIGN KEY(activity_id, question_id) REFERENCES questions(activity_id, id),
                UNIQUE(activity_id, question_id, group_id));
            CREATE TABLE IF NOT EXISTS sheet_sources (
                activity_id TEXT PRIMARY KEY REFERENCES activities(id), source_json TEXT NOT NULL,
                exported_at REAL);
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY, activity_id TEXT NOT NULL REFERENCES activities(id),
                group_id TEXT NOT NULL REFERENCES groups(id), request_id TEXT NOT NULL, body TEXT NOT NULL,
                UNIQUE(activity_id, group_id, request_id));
            CREATE INDEX IF NOT EXISTS chat_activity_order ON chat_messages(activity_id,id);
            CREATE TRIGGER IF NOT EXISTS clear_finished_chat AFTER UPDATE OF phase ON activities
            WHEN NEW.phase='results' AND OLD.phase<>NEW.phase
            BEGIN
                DELETE FROM chat_messages WHERE activity_id=NEW.id;
            END;
        """)
        self._init_extras()

    def close(self):
        with self.lock:
            self.db.close()

    def teacher_key(self, token):
        with self.lock:
            return self._auth(token, "teacher")["token_hash"]

    def teacher_active(self, owner):
        with self.lock:
            return bool(self.db.execute("SELECT 1 FROM sessions WHERE token_hash=? AND role='teacher' AND expires_at>?",
                                        (owner,time.time())).fetchone())

    def check_sheet_course(self, sid, course):
        with self.lock:
            if self.db.execute("""
                SELECT 1 FROM sheet_sources s JOIN lessons l ON s.activity_id=l.aid
                WHERE json_extract(s.source_json, '$.spreadsheet_id')=? AND l.course<>? LIMIT 1
            """, (sid, course)).fetchone():
                raise QuizError(409, "此副本已匯入其他課程，請為本課程建立另一份副本。")

    def create_from_source(self, token, title, source, *, bind_course=None):
        with self.lock, self.db:
            if bind_course:
                self.check_sheet_course(source["spreadsheet_id"], bind_course)
            result = self.create(token, title, [t["question"] for t in source["targets"]], _commit=False)
            self.db.executemany("UPDATE question_meta SET unit_id=?, prompt=? WHERE activity_id=? AND question_id=?",
                                [(t.get("unit",t["question"]),t.get("prompt", ""),result["id"],t["question"]) for t in source["targets"]])
            self.db.execute("INSERT INTO sheet_sources(activity_id,source_json) VALUES(?,?)",
                            (result["id"],json.dumps(source,ensure_ascii=False)))
            return result

    def export_context(self, token, aid):
        with self.lock:
            self._auth(token, "teacher", aid)
            return self._sheet_export_context(aid)

    def _sheet_export_context(self, aid):
        with self.lock:
            activity = self._activity(aid)
            closed = [r['id'] for r in self.db.execute('SELECT id FROM questions WHERE activity_id=? ORDER BY ordinal', (aid,))
                      if self._reviewable(activity, r['id'])]
            if not closed:
                raise QuizError(409, "請先關閉一題或結束搶答，再寫回答案。")
            row = self.db.execute("SELECT source_json FROM sheet_sources WHERE activity_id=?",(aid,)).fetchone()
            if not row:
                raise QuizError(409, "這是手動題號活動，沒有可寫回的 Google Sheet。")
            winners = self._sheet_answers(activity)
            source = json.loads(row["source_json"])
            source['_closed_questions'] = closed
            return source, winners

    def _record_export(self, aid, expected, sheet_id, closed_questions):
        with self.lock, self.db:
            source = json.loads(self.db.execute("SELECT source_json FROM sheet_sources WHERE activity_id=?",(aid,)).fetchone()[0])
            source.setdefault("last_export", {}).update(expected)
            source.pop('pending_export', None)
            source["sheet_id"] = sheet_id
            activity=self._activity(aid)
            winners=self._sheet_answers(activity)
            desired={t['question']:(winners[t['question']] if t['question'] in winners else t['original'])
                     for t in source['targets'] if self._reviewable(activity,t['question']) and (t['question'] in winners or t['question'] in expected)}
            closed_now = [r['id'] for r in self.db.execute(
                'SELECT id FROM questions WHERE activity_id=? ORDER BY ordinal', (aid,)
            ) if self._reviewable(activity, r['id'])]
            current = desired == expected and closed_now == closed_questions
            self.db.execute("UPDATE sheet_sources SET source_json=?,exported_at=? WHERE activity_id=?",
                            (json.dumps(source,ensure_ascii=False),time.time() if current else None,aid))
            return current

    def _journal_export(self, aid, expected, previous, sheet_id):
        with self.lock, self.db:
            source=json.loads(self.db.execute('SELECT source_json FROM sheet_sources WHERE activity_id=?',(aid,)).fetchone()[0])
            source['pending_export']={'expected':expected,'previous':previous,'sheet_id':sheet_id}
            self.db.execute('UPDATE sheet_sources SET source_json=?,exported_at=NULL WHERE activity_id=?',(json.dumps(source,ensure_ascii=False),aid))

    def _recover_export(self, aid, observed):
        with self.lock, self.db:
            source=json.loads(self.db.execute('SELECT source_json FROM sheet_sources WHERE activity_id=?',(aid,)).fetchone()[0])
            source.setdefault('last_export',{}).update(observed)
            source.pop('pending_export',None)
            self.db.execute('UPDATE sheet_sources SET source_json=?,exported_at=NULL WHERE activity_id=?',(json.dumps(source,ensure_ascii=False),aid))

    def _token(self, role, activity_id=None, group_id=None):
        raw = secrets.token_urlsafe(32)
        self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        self.db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (
            hashlib.sha256(raw.encode()).hexdigest(), role, activity_id, group_id,
            time.time() + 86400))
        return {"token": raw, "role": role, "activity_id": activity_id}

    def _auth(self, token, role=None, activity_id=None):
        if not isinstance(token, str):
            raise QuizError(401, "請先登入。")
        row = self.db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                              (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if row is None:
            raise QuizError(401, "登入已失效，請重新進入。")
        if role and row["role"] != role:
            raise QuizError(403, "此操作需要教師或指定角色權限。")
        if self.courses:
            scope = self.courses.scope(token)
            if activity_id:
                self.courses.access(scope, activity_id)
        if activity_id and row["role"] == "student" and row["activity_id"] != activity_id:
            raise QuizError(403, "無法存取其他活動。")
        return row

    def chat_student(self, session):
        return session["role"] == "student" and (
            not self.courses or self.courses.student_workspace_session(session["token_hash"])
        )

    def _chat_access(self, token, aid):
        session = self._auth(token, "student", aid)
        if not self.chat_student(session):
            raise QuizError(403, "公用頻道僅開放給本場學生。")
        if self._activity(aid)["phase"] != "active":
            raise QuizError(409, "公用頻道只在搶答進行中開放。")
        return session["group_id"]

    @expire_first
    def chat_messages(self, token, aid, after):
        with self.lock:
            self._chat_access(token, aid)
            if not isinstance(after, str) or not after.isascii() or not after.isdecimal() or len(after) > 19 or int(after) > 2**63-1:
                raise QuizError(400, "訊息位置無效。")
            rows = self.db.execute(
                "SELECT m.id,g.name AS group_name,m.body FROM chat_messages m JOIN groups g ON g.id=m.group_id "
                "WHERE m.activity_id=? AND m.id>? ORDER BY m.id LIMIT 100", (aid, int(after)),
            )
            return {"messages": [dict(row) for row in rows]}

    @expire_first
    def post_chat(self, token, aid, body, request_id):
        with self.lock, self.db:
            gid = self._chat_access(token, aid)
            body = text(body, "訊息", 500)
            request_id = text(request_id, "發言識別碼", 64)
            key = (aid, gid, request_id)
            self.db.execute(
                "INSERT INTO chat_messages(activity_id,group_id,request_id,body) VALUES(?,?,?,?) "
                "ON CONFLICT(activity_id,group_id,request_id) DO NOTHING", (*key, body),
            )
            saved = self.db.execute(
                "SELECT id,body FROM chat_messages WHERE activity_id=? AND group_id=? AND request_id=?", key,
            ).fetchone()
            if saved["body"] != body:
                raise QuizError(409, "這次發言已送出。")
            return {"id": saved["id"]}

    def login(self, password, client="local"):
        with self.lock, self.db:
            now = time.monotonic()
            attempts = [t for t in self.login_attempts.get(client, []) if now - t < 60]
            if len(attempts) >= 10:
                raise QuizError(429, "登入嘗試太頻繁，請稍後再試。")
            candidate = hashlib.sha256(str(password).encode()).digest()
            if not hmac.compare_digest(candidate, self.password_hash):
                self.login_attempts[client] = attempts + [now]
                raise QuizError(401, "教師密碼不正確。")
            self.login_attempts.pop(client, None)
            return self._token("teacher")

    def logout(self, token):
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE token_hash=?",
                            (hashlib.sha256(token.encode()).hexdigest(),))
            return {"ok": True}

    def create(self, token, title, questions, _commit=True):
        from contextlib import nullcontext
        with self.lock, self.db if _commit else nullcontext():
            self._auth(token, "teacher")
            title = text(title, "活動名稱", 100)
            if not isinstance(questions, list) or not 1 <= len(questions) <= 100:
                raise QuizError(400, "請提供 1～100 個題號。")
            questions = [text(q, "題號", 40) for q in questions]
            if len(set(questions)) != len(questions):
                raise QuizError(400, "題號不可重複。")
            aid = secrets.token_hex(12)
            while True:
                code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
                if not self.db.execute("SELECT 1 FROM activities WHERE code=?", (code,)).fetchone():
                    break
            self.db.execute("INSERT INTO activities(id,code,title,created_at) VALUES(?,?,?,?)",
                            (aid, code, title, time.time()))
            self.db.executemany("INSERT INTO questions VALUES(?,?,?)",
                                [(aid, q, i) for i, q in enumerate(questions)])
            self._new_options(aid)
            if self.courses:
                scope = self.courses.scope(token)
                if scope['kind'] != 'owner':
                    raise QuizError(403, '只有課程老師可建立活動。')
                self.db.execute('INSERT INTO lessons VALUES(?,?)', (aid, scope['course']))
            return {"id": aid, "code": code}

    def join(self, code, group):
        code, group = text(code, "活動代碼", 6).upper(), text(group, "小組名稱", 40)
        with self.lock, self.db:
            activity = self.db.execute("SELECT * FROM activities WHERE code=?", (code,)).fetchone()
            if activity is None:
                raise QuizError(404, "找不到活動，請確認代碼。")
            existing = self.db.execute("SELECT id FROM groups WHERE activity_id=? AND normalized_name=?",
                                       (activity["id"], group.casefold())).fetchone()
            gid = existing["id"] if existing else secrets.token_hex(12)
            if not existing:
                self.db.execute("INSERT INTO groups VALUES(?,?,?,?)",
                                (gid, activity["id"], group, group.casefold()))
            return self._token("student", activity["id"], gid)

    @expire_first
    def activities(self, token):
        with self.lock:
            self._auth(token, "teacher")
            if self.courses:
                return self.courses.rows('SELECT a.* FROM activities a JOIN lessons l ON l.aid=a.id WHERE l.course=? ORDER BY created_at DESC', self.courses.scope(token)['course'])
            return [dict(r) for r in self.db.execute("SELECT * FROM activities ORDER BY created_at DESC")]

    def _activity(self, aid):
        row = self.db.execute("SELECT * FROM activities WHERE id=?", (aid,)).fetchone()
        if row is None:
            raise QuizError(404, "找不到這個活動。")
        return row

    @expire_first
    def transition(self, token, aid, target):
        with self.lock, self.db:
            self._auth(token, "teacher")
            activity = self._activity(aid)
            if target not in ("active", "results"):
                raise QuizError(400, "無效階段。")
            if activity["phase"] == target:
                return {"phase": target}
            required = "preparing" if target == "active" else "active"
            if activity["phase"] != required:
                raise QuizError(409, "目前階段不允許此操作。重新搶答請建立新活動。")
            field = "started_at" if target == "active" else "ended_at"
            self.db.execute(f"UPDATE activities SET phase=?, {field}=? WHERE id=?",
                            (target, time.time(), aid))
            if self._options(aid)["mode"] == "sequential":
                if target == "active": self._open_round(aid, 0)
                else: self._close_round(aid)
            else:
                if target == 'active':
                    self.db.execute('UPDATE question_meta SET opened_at=(SELECT started_at FROM activities WHERE id=?) WHERE activity_id=?', (aid, aid))
                duration=self._options(aid)['duration_seconds']
                self.db.execute('UPDATE activity_options SET deadline=? WHERE activity_id=?', (time.time()+duration if target=='active' and duration else None,aid))
            return {"phase": target}

    def _own_answer(self, row, activity=None):
        # Do not expose the global id: gaps would reveal other groups' submissions.
        answer = {k: row[k] for k in ("question_id", "text", "received_at", "elapsed_ms", "elapsed_basis", "stake", "verdict")}
        if activity is not None and not self._reviewable(activity, row['question_id']):
            answer['verdict'] = 'withheld'
        return answer

    @expire_first
    def submit(self, token, aid, question, answer, stake=0, *, _bundle=False, _commit=True, _received=None):
        from contextlib import nullcontext
        with self.lock, self.db if _commit else nullcontext():
            session = self._auth(token, "student", aid)
            activity = self._activity(aid)
            if activity["phase"] != "active":
                raise QuizError(409, "目前不在作答階段，答案未送出。")
            question = text(question, "題號", 40)
            if type(stake) is not int or not 0 <= stake <= 3:
                raise QuizError(400, "下注必須是 0～3 的整數；0 表示不押。")
            received = time.time() if _received is None else _received
            self._submission_gate(activity, session, question, received)
            if not _bundle and any(question in qs and len(qs)>1 for qs in self._units(aid).values()):
                raise QuizError(409, "題組必須一次送出全部子題。")
            if not self.db.execute("SELECT 1 FROM questions WHERE activity_id=? AND id=?",
                                   (aid, question)).fetchone():
                raise QuizError(404, "題號不存在。")
            answer, verdict = self._grade_submission(aid, question, answer, stake)
            previous = self.db.execute("SELECT * FROM answers WHERE activity_id=? AND question_id=? AND group_id=?",
                                       (aid, question, session["group_id"])).fetchone()
            if previous:
                if previous["text"] != answer or previous["stake"] != stake:
                    raise QuizError(409, "本組已送出此題，不能修改答案。")
                return self._own_answer(previous, activity)
            opened = self.db.execute('SELECT opened_at FROM question_meta WHERE activity_id=? AND question_id=?', (aid, question)).fetchone()['opened_at']
            basis = 'question' if opened is not None else 'activity'
            elapsed = max(0, round((received - (opened if opened is not None else activity["started_at"])) * 1000))
            cursor = self.db.execute("INSERT INTO answers(activity_id,question_id,group_id,text,received_at,elapsed_ms,elapsed_basis,stake,verdict) VALUES(?,?,?,?,?,?,?,?,?)",
                                     (aid, question, session["group_id"], answer, received, elapsed, basis, stake, verdict))
            if self.courses:
                self.db.execute('INSERT INTO submitters VALUES(?,?)', (cursor.lastrowid, self.courses.scope(token)['uid']))
            return self._own_answer(self.db.execute("SELECT * FROM answers WHERE id=?", (cursor.lastrowid,)).fetchone(), activity)

    def _teacher_answers(self, aid):
        rows = [dict(r) for r in self.db.execute(
            "SELECT a.*,g.name AS group_name FROM answers a JOIN groups g ON g.id=a.group_id WHERE a.activity_id=? ORDER BY a.id", (aid,))]
        if self.courses:
            answers = {a['id']: a for a in rows}
            for row in self.courses.rows('SELECT s.answer,p.email FROM submitters s JOIN people p ON p.uid=s.uid JOIN answers a ON a.id=s.answer WHERE a.activity_id=?', aid):
                answers[row['answer']]['author'] = row['email']
            for row in self.courses.rows('SELECT g.*,p.email FROM grade_log g JOIN people p ON p.uid=g.uid JOIN answers a ON a.id=g.answer WHERE a.activity_id=? ORDER BY revision', aid):
                answers[row['answer']].setdefault('reviews', []).append(row)
        return rows

    @expire_first
    def snapshot(self, token, aid):
        with self.lock:
            session = self._auth(token, activity_id=aid)
            activity = dict(self._activity(aid))
            activity["role"] = session["role"]
            activity["questions"] = [r["id"] for r in self.db.execute(
                "SELECT id FROM questions WHERE activity_id=? ORDER BY ordinal", (aid,))]
            if session["role"] == "teacher":
                source = self.db.execute("SELECT source_json,exported_at FROM sheet_sources WHERE activity_id=?",(aid,)).fetchone()
                if source:
                    info = json.loads(source["source_json"])
                    activity["source"] = {"sheet_title":info["sheet_title"], "url":f"https://docs.google.com/spreadsheets/d/{info['spreadsheet_id']}/edit",
                                          "exported_at":source["exported_at"], "export_stale":bool(info.get("last_export")) and not source["exported_at"]}
                    activity["source"]["sync"] = self.sheet_sync_states.get(aid, {
                        'state': 'synced' if source["exported_at"] else 'idle',
                        'message': '已完成學習單同步。' if source["exported_at"] else '學習單會在關題後同步。'})
                activity["groups"] = [dict(r) for r in self.db.execute(
                    "SELECT id,name FROM groups WHERE activity_id=? ORDER BY name", (aid,))]
                activity["answers"] = self._teacher_answers(aid)
            else:
                group = self.db.execute("SELECT name FROM groups WHERE id=?", (session["group_id"],)).fetchone()
                activity["group_name"] = group["name"]
                activity["answers"] = [self._own_answer(r, activity) for r in self.db.execute(
                    "SELECT * FROM answers WHERE activity_id=? AND group_id=? ORDER BY id", (aid, session["group_id"]))]
            if activity["phase"] == "results":
                winners = {}
                for r in self._winner_rows(aid).values():
                    winners.setdefault(r["question_id"], {**self._own_answer(r), "group_name": r["group_name"]})
                answered={r['question_id'] for r in self.db.execute('SELECT DISTINCT question_id FROM answers WHERE activity_id=?',(aid,))}
                activity["results"] = [{"question_id": q, "winner": winners.get(q), "has_answers":q in answered} for q in activity["questions"]]
            return self._extra_snapshot(activity, session)
