"""Google identities, per-course memberships and restricted quiz sessions."""

import hashlib
import hmac
import secrets
import time

from quiz_service import QuizError, text


def firebase_identity(token, project):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import verify_firebase_token

    if not token or len(token) > 16384:
        raise QuizError(401, "請先用 Google 登入。")
    try:
        claims = verify_firebase_token(token, Request(), audience=project)
    except Exception:
        raise QuizError(401, "Google 登入無法驗證，請重新登入。") from None
    if (
        claims.get("iss") != "https://securetoken.google.com/" + project
        or claims.get("firebase", {}).get("sign_in_provider") != "google.com"
        or claims.get("email_verified") is not True
        or not claims.get("email")
        or not claims.get("sub")
    ):
        raise QuizError(403, "需要使用本專案已驗證的 Google 帳號。")
    return claims["sub"], claims["email"].casefold()


class Courses:
    @staticmethod
    def team_password(data):
        password = data.get("password")
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise QuizError(400, "小組密碼需為 8～128 字元。")
        return password

    def __init__(self, service, config, admin_uid, verify=firebase_identity, *, admin_uids=()):
        if not isinstance(admin_uids, (list, tuple)):
            raise ValueError("adminUids 必須是 UID 陣列。")
        uids = list(admin_uids)
        if admin_uid is not None and admin_uid != "":
            uids.append(admin_uid)
        if any(not isinstance(uid, str) or not uid.strip() or len(uid) > 128 for uid in uids):
            raise ValueError("管理員 UID 必須是 1～128 字元的非空白字串。")
        self.admin_uids = frozenset(uids)
        self.s, self.db, self.config, self.verify = service, service.db, config, verify
        self.attempts = {}
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS auth_project(project TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS people(uid TEXT PRIMARY KEY, email TEXT NOT NULL, teacher INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL REFERENCES people(uid));
            CREATE TABLE IF NOT EXISTS assistants(course TEXT REFERENCES courses(id), uid TEXT REFERENCES people(uid), PRIMARY KEY(course,uid));
            CREATE TABLE IF NOT EXISTS lessons(aid TEXT PRIMARY KEY REFERENCES activities(id), course TEXT NOT NULL REFERENCES courses(id));
            CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY, course TEXT NOT NULL REFERENCES courses(id), name TEXT NOT NULL, norm TEXT NOT NULL, salt BLOB NOT NULL, digest BLOB NOT NULL, UNIQUE(course,norm));
            CREATE TABLE IF NOT EXISTS members(course TEXT REFERENCES courses(id), uid TEXT REFERENCES people(uid), team TEXT REFERENCES teams(id), PRIMARY KEY(course,uid));
            CREATE TABLE IF NOT EXISTS attendance(team TEXT REFERENCES teams(id), aid TEXT REFERENCES activities(id), gid TEXT UNIQUE REFERENCES groups(id), PRIMARY KEY(team,aid));
            CREATE TABLE IF NOT EXISTS course_sessions(hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE, uid TEXT REFERENCES people(uid), course TEXT REFERENCES courses(id), kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS submitters(answer INTEGER PRIMARY KEY REFERENCES answers(id), uid TEXT NOT NULL REFERENCES people(uid));
            CREATE TABLE IF NOT EXISTS grade_log(answer INTEGER REFERENCES answers(id), revision INTEGER, uid TEXT REFERENCES people(uid), verdict TEXT, stamp REAL, PRIMARY KEY(answer,revision));
        """)
        existing = self.db.execute("SELECT project FROM auth_project").fetchone()
        if existing and existing[0] != config["projectId"]:
            raise ValueError("此資料庫已綁定另一個 Firebase 專案。")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO auth_project VALUES(?)", (config["projectId"],))
        service.courses = self

    def one(self, sql, *args):
        return self.db.execute(sql, args).fetchone()

    def rows(self, sql, *args):
        return [dict(r) for r in self.db.execute(sql, args)]

    def scope(self, token):
        record = self.one(
            "SELECT c.* FROM course_sessions c JOIN sessions s ON s.token_hash=c.hash WHERE c.hash=? AND s.expires_at>?",
            hashlib.sha256(token.encode()).hexdigest(),
            time.time(),
        )
        if not record:
            raise QuizError(401, "請從課程首頁重新進入。")
        return record

    def student_workspace_session(self, token_hash):
        member = self.one(
            "SELECT s.uid FROM course_sessions s JOIN people p ON p.uid=s.uid "
            "WHERE s.hash=? AND s.kind='student' AND p.teacher=0 "
            "AND NOT EXISTS (SELECT 1 FROM assistants a WHERE a.uid=s.uid)", token_hash,
        )
        return member is not None and member["uid"] not in self.admin_uids

    def access(self, scope, aid):
        if not self.one("SELECT 1 FROM lessons WHERE aid=? AND course=?", aid, scope["course"]):
            raise QuizError(403, "無法存取其他課程的活動。")

    def role(self, uid, course):
        if self.one("SELECT 1 FROM courses WHERE id=? AND owner=?", course, uid):
            return "owner"
        if self.one("SELECT 1 FROM assistants WHERE course=? AND uid=?", course, uid):
            return "assistant"
        return None

    def dispatch(self, token, action, data):
        uid, email = self.verify(token, self.config["projectId"])
        with self.s.lock, self.db:
            self.db.execute(
                "INSERT INTO people(uid,email) VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET email=excluded.email",
                (uid, email),
            )
            return self.account(uid, email, action, data)

    def account(self, uid, email, action, data):
        course = text(data.get("course", "-"), "課程代碼", 64).upper()
        role = self.role(uid, course)
        team = self.one(
            "SELECT t.* FROM members m JOIN teams t ON t.id=m.team WHERE m.uid=? AND m.course=?", uid, course
        )
        teacher = bool(self.one("SELECT teacher FROM people WHERE uid=?", uid)[0])
        admin = uid in self.admin_uids
        if action == "home":
            result = {
                "uid": uid,
                "email": email,
                "admin": admin,
                "teacher": teacher,
                "teaching": self.rows(
                    "SELECT id,title,owner FROM courses WHERE owner=? OR id IN (SELECT course FROM assistants WHERE uid=?) ORDER BY rowid DESC",
                    uid,
                    uid,
                ),
                "studying": self.rows(
                    "SELECT c.id,c.title,t.name FROM members m JOIN courses c ON c.id=m.course JOIN teams t ON t.id=m.team WHERE uid=?",
                    uid,
                ),
            }
            if admin:
                result["legacy"] = self.rows(
                    "SELECT id,title FROM activities WHERE id NOT IN (SELECT aid FROM lessons)"
                )
                result["destinations"] = self.rows(
                    "SELECT c.id,c.title,p.email FROM courses c JOIN people p ON p.uid=c.owner"
                )
            return result
        if action in ("grant", "assistant"):
            if not (admin if action == "grant" else role == "owner"):
                raise QuizError(403, "沒有指派權限。")
            target = text(data.get("uid"), "對方的帳號 UID", 128)
            if not self.one("SELECT 1 FROM people WHERE uid=?", target):
                raise QuizError(404, "請對方先登入一次，再從首頁複製 UID。")
            if action == "grant":
                self.db.execute("UPDATE people SET teacher=1 WHERE uid=?", (target,))
            else:
                self.db.execute("INSERT OR IGNORE INTO assistants VALUES(?,?)", (course, target))
        elif action == "claim":
            if not admin:
                raise QuizError(403, "限管理員接管舊活動。")
            aid = text(data.get("aid"), "活動", 64)
            if not self.one("SELECT 1 FROM courses WHERE id=?", course) or not self.one(
                "SELECT 1 FROM activities WHERE id=? AND id NOT IN (SELECT aid FROM lessons)", aid
            ):
                raise QuizError(409, "請選擇未分配活動及既有課程。")
            self.db.execute("INSERT INTO lessons VALUES(?,?)", (aid, course))
        elif action == "create-course":
            if not teacher:
                raise QuizError(403, "請先由管理員指定教師資格。")
            course = secrets.token_hex(5).upper()
            self.db.execute(
                "INSERT INTO courses VALUES(?,?,?)", (course, text(data.get("title"), "課程名稱", 100), uid)
            )
        elif action in ("create-team", "join-team"):
            self.register_team(uid, course, team, action, data)
        elif action == "reset-password":
            if role != "owner":
                raise QuizError(403, "只有本課程的授課老師可以重設小組密碼。")
            tid = text(data.get("team"), "小組", 64)
            password = self.team_password(data)
            salt = secrets.token_bytes(16)
            digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
            updated = self.db.execute("UPDATE teams SET salt=?,digest=? WHERE course=? AND id=?",
                                      (salt, digest, course, tid))
            if not updated.rowcount:
                raise QuizError(404, "這門課沒有這個小組。")
        elif action == "history-detail":
            aid = text(data.get("aid"), "活動", 64)
            self.access({"course": course}, aid)
            if data.get("staff") is True:
                if not role:
                    raise QuizError(403, "只有本課程教學人員可以查看批改紀錄。")
                return {"answers": self.s._teacher_answers(aid)}
            attendance = team and self.one("SELECT gid FROM attendance WHERE team=? AND aid=?", team["id"], aid)
            if not attendance:
                raise QuizError(403, "沒有本組的活動紀錄。")
            activity = self.s._activity(aid)
            rows = self.rows("SELECT * FROM answers WHERE activity_id=? AND group_id=? ORDER BY id",
                             aid, attendance["gid"])
            return {"answers": [self.s._own_answer(row, activity) for row in rows]}
        elif action in ("staff-room", "student-room"):
            return self.open_room(uid, course, role, team, action, data)
        elif action == "course":
            return self.course_history(course, role, team, data.get("staff") is True)
        elif action == "leaderboard":
            if role != "owner" and (
                not team or teacher or admin or self.one("SELECT 1 FROM assistants WHERE uid=?", uid)
            ):
                raise QuizError(403, "無此課程排行榜權限。")
            return self.course_leaderboard(course)
        else:
            raise QuizError(404, "未知操作。")
        return {"ok": True, "course": course}

    def register_team(self, uid, course, team, action, data):
        if not self.one("SELECT 1 FROM courses WHERE id=?", course):
            raise QuizError(404, "找不到課程。")
        if team:
            raise QuizError(409, "你已加入本課程的小組。")
        name = text(data.get("name"), "小組名稱", 40)
        password = self.team_password(data)
        saved = self.one("SELECT * FROM teams WHERE course=? AND norm=?", course, name.casefold())
        if action == "create-team" and saved:
            raise QuizError(409, "本課程已有同名小組。")
        key = (uid, course)
        attempts = [t for t in self.attempts.get(key, []) if t > time.monotonic() - 60]
        if len(attempts) >= 8:
            raise QuizError(429, "密碼嘗試過多，請稍後再試。")
        salt = saved["salt"] if saved else secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        if action == "join-team" and (not saved or not hmac.compare_digest(digest, saved["digest"])):
            self.attempts[key] = attempts + [time.monotonic()]
            raise QuizError(403, "小組名稱或密碼錯誤。")
        tid = saved["id"] if saved else secrets.token_hex(12)
        if not saved:
            self.db.execute(
                "INSERT INTO teams VALUES(?,?,?,?,?,?)", (tid, course, name, name.casefold(), salt, digest)
            )
        self.db.execute("INSERT INTO members VALUES(?,?,?)", (course, uid, tid))
        self.attempts.pop(key, None)

    def open_room(self, uid, course, role, team, action, data):
        if action == "staff-room":
            if not role:
                raise QuizError(403, "你不是此課程的教學人員。")
            aid = data.get("aid")
            if aid is not None:
                aid = text(aid, "活動", 64)
                self.access({"course": course}, aid)
            if role == "assistant" and not aid:
                raise QuizError(403, "請選擇要批改的活動。")
            room = self.s._token("teacher")
        else:
            if not team:
                raise QuizError(403, "請先加入課程小組。")
            aid = text(data.get("aid"), "活動", 64)
            self.access({"course": course}, aid)
            record = self.one("SELECT gid FROM attendance WHERE team=? AND aid=?", team["id"], aid)
            if not record:
                if self.s._activity(aid)["phase"] == "results":
                    raise QuizError(403, "本組未參與此場活動。")
                gid = secrets.token_hex(12)
                label = team["name"]
                if self.one(
                    "SELECT 1 FROM groups WHERE activity_id=? AND normalized_name=?", aid, label.casefold()
                ):
                    label = label + "（" + team["id"] + "）"
                self.db.execute("INSERT INTO groups VALUES(?,?,?,?)", (gid, aid, label, label.casefold()))
                self.db.execute("INSERT INTO attendance VALUES(?,?,?)", (team["id"], aid, gid))
            else:
                gid = record["gid"]
            room = self.s._token("student", aid, gid)
        self.db.execute(
            "INSERT INTO course_sessions VALUES(?,?,?,?)",
            (
                hashlib.sha256(room["token"].encode()).hexdigest(),
                uid,
                course,
                role if action == "staff-room" else "student",
            ),
        )
        return {
            **room,
            "activity_id": aid,
            "course": course,
            "assistant": action == "staff-room" and role == "assistant",
        }

    def priority_sources(self, course):
        return self.rows(
            "SELECT a.id,a.title,a.ended_at FROM activities a JOIN lessons l ON l.aid=a.id "
            "WHERE l.course=? AND a.phase='results' ORDER BY a.ended_at DESC,a.id", course,
        )

    def check_priority_source(self, token, source):
        scope = self.scope(token)
        if scope["kind"] != "owner":
            raise QuizError(403, "只有授課老師可指定保底來源。")
        self.access(scope, source)
        if self.s._activity(source)["phase"] != "results":
            raise QuizError(409, "請選擇同一課程已結束的場次。")

    def prior_priority_groups(self, aid, source):
        matches = self.rows(
            "SELECT current.gid, prior.gid AS prior_gid FROM attendance current "
            "JOIN attendance prior ON prior.team=current.team "
            "WHERE current.aid=? AND prior.aid=?", aid, source,
        )
        points = self.s._published_points(self.s._activity(source), self.s._units(source), self.s._options(source))
        totals = {row["gid"]: self.s._sum_points(points.get(row["prior_gid"], {}))["total"] for row in matches}
        lowest = min(totals.values(), default=None)
        return [gid for gid, score in totals.items() if score == lowest]

    def course_leaderboard(self, course):
        totals = {
            row["id"]: {"group_name": row["name"], "score": 0}
            for row in self.rows("SELECT id,name FROM teams WHERE course=?", course)
        }
        lessons = self.rows(
            "SELECT a.id,a.phase FROM activities a JOIN lessons l ON l.aid=a.id "
            "WHERE l.course=? AND a.phase IN ('active','results')", course,
        )
        by_lesson = {}
        for row in self.rows(
            "SELECT at.aid,at.gid,at.team FROM attendance at JOIN teams t ON t.id=at.team "
            "JOIN lessons l ON l.aid=at.aid WHERE t.course=? AND l.course=t.course", course,
        ):
            by_lesson.setdefault(row["aid"], {})[row["gid"]] = row["team"]
        for lesson in lessons:
            aid = lesson["id"]
            groups = by_lesson.get(aid)
            if groups:
                points = self.s._published_points(lesson, self.s._units(aid), self.s._options(aid))
                for gid, units in points.items():
                    if gid in groups:
                        totals[groups[gid]]["score"] += self.s._sum_points(units)["total"]
        return {"rows": self.s._rank_scores(list(totals.values()))}

    def course_history(self, course, role, team, staff):
        if not (role if staff else team):
            raise QuizError(403, "無此課程權限。")
        lessons = self.rows(
            "SELECT a.id,a.title,a.phase,COALESCE(a.started_at,a.created_at) AS activity_date "
            "FROM activities a JOIN lessons l ON l.aid=a.id WHERE l.course=? ORDER BY activity_date DESC",
            course,
        )
        total = 0
        if not staff:
            for item in lessons:
                aid = item["id"]
                group = self.one("SELECT gid FROM attendance WHERE team=? AND aid=?", team["id"], aid)
                item["score"] = 0
                item["attended"] = bool(group)
                if group:
                    pts = self.s._published_points(item, self.s._units(aid), self.s._options(aid))
                    item["score"] = self.s._sum_points(pts.get(group["gid"], {}))["total"]
                total += item["score"]
        result = {"lessons": lessons, "total": total, "role": role if staff else "student"}
        if staff and role == "owner":
            result["teams"] = self.rows("SELECT id,name FROM teams WHERE course=? ORDER BY name", course)
        return result
