import json
import threading
import time
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import make_server
from course_accounts import Courses, firebase_identity
from quiz_service import QuizError, QuizService


class CourseTests(unittest.TestCase):
    def setUp(self):
        self.s = QuizService(":memory:", "old")
        self.addCleanup(self.s.close)
        self.old_token = self.s.login("old")["token"]
        self.legacy = self.s.create(self.old_token, "舊活動", ["1"])["id"]
        web = {"projectId": "demo", "authDomain": "demo.firebaseapp.com", "apiKey": "web", "appId": "web"}
        self.accounts = Courses(self.s, web, "admin", lambda uid, project: (uid, uid + "@example.org"))
        self.call("teacher", "home")
        self.call("admin", "grant", uid="teacher")
        self.course = self.call("teacher", "create-course", title="自然")["course"]
        self.other = self.call("teacher", "create-course", title="英文")["course"]
        self.teacher = self.room("teacher")
        self.aid = self.s.create(self.teacher, "第一堂", ["1"])["id"]

    def call(self, actor, action, **data):
        return self.accounts.dispatch(actor, action, data)

    def room(self, actor, **data):
        return self.call(actor, "staff-room", course=self.course, **data)["token"]

    def member(self, actor, create=False, course=None, password="class123"):
        return self.call(
            actor,
            "create-team" if create else "join-team",
            course=course or self.course,
            name="第一組",
            password=password,
        )

    def student(self, actor):
        return self.call(actor, "student-room", course=self.course, aid=self.aid)["token"]

    def test_chat_available_only_to_student_accounts(self):
        self.member("student", True)
        self.member("helper")
        self.member("teacher")
        self.member("admin")
        self.s.transition(self.teacher, self.aid, "active")
        student, helper = self.student("student"), self.student("helper")
        self.s.post_chat(student, self.aid, "學生討論", "first")
        self.assertTrue(self.s.snapshot(helper, self.aid)["chat_available"])
        self.call("teacher", "assistant", course=self.course, uid="helper")
        for token in (helper, self.student("teacher"), self.student("admin"), self.room("helper", aid=self.aid)):
            self.assertFalse(self.s.snapshot(token, self.aid).get("chat_available"))
            with self.assertRaises(QuizError):
                self.s.chat_messages(token, self.aid, "0")
            with self.assertRaises(QuizError):
                self.s.post_chat(token, self.aid, "test", "second")
        self.assertEqual(self.s.chat_messages(student, self.aid, "0")["messages"][0]["group_name"], "第一組")

    def test_course_leaderboard_scope(self):
        self.assertEqual(self.call("teacher", "leaderboard", course=self.course)["rows"], [])
        self.member("student", True)
        self.call("mentor", "home")
        self.call("admin", "grant", uid="mentor")
        self.call("teacher", "assistant", course=self.course, uid="mentor")
        self.call("helper", "home")
        self.call("teacher", "assistant", course=self.other, uid="helper")
        self.member("helper")
        for actor, course in (("student", self.other), ("outsider", self.course), ("admin", self.course),
                              ("mentor", self.course), ("helper", self.course)):
            with self.subTest(actor=actor), self.assertRaises(QuizError) as error:
                self.call(actor, "leaderboard", course=course, staff=False)
            self.assertEqual(error.exception.status, 403)

    def test_course_leaderboard_publication_ties_and_regrade(self):
        def board(actor="A", course=None):
            return self.call(actor, "leaderboard", course=course or self.course)["rows"]

        def standings():
            return [(r["group_name"], r["score"], r["rank"]) for r in board()]

        for name in "ABC":
            self.call(name, "create-team", course=self.course, name=name, password="class123")
        self.call("partner", "join-team", course=self.course, name="A", password="class123")
        self.call("A", "create-team", course=self.other, name="A", password="class123")
        self.s.question_settings(self.teacher, self.aid, "1", True, [
            {"question": "1", "type": "choice", "options": ["是", "否"], "correct_index": 0},
        ])
        self.s.transition(self.teacher, self.aid, "active")
        self.s.submit(self.student("A"), self.aid, "1", "是", 1)
        self.s.submit(self.student("B"), self.aid, "1", "是", 3)
        self.assertEqual(standings(), [("A", 0, 1), ("B", 0, 1), ("C", 0, 1)])
        self.s.transition(self.teacher, self.aid, "results")
        self.assertEqual(standings(), [("A", 5, 1), ("B", 5, 1), ("C", 0, 3)])
        self.assertEqual(board("teacher"), board("partner"))
        answer = self.s.snapshot(self.teacher, self.aid)["answers"][0]
        self.s.review(self.teacher, self.aid, answer["id"], "incorrect", answer["review_revision"])
        self.assertEqual(standings(), [("B", 7, 1), ("C", 0, 2), ("A", -1, 3)])

        second = self.s.create(self.teacher, "第二堂", ["1", "2"])["id"]
        self.s.configure(self.teacher, second, "sequential")
        self.s.question_settings(self.teacher, second, "1", True, [
            {"question": "1", "type": "choice", "options": ["是", "否"], "correct_index": 0},
        ])
        token = self.call("partner", "student-room", course=self.course, aid=second)["token"]
        self.s.transition(self.teacher, second, "active")
        self.s.submit(token, second, "1", "是", 2)
        self.assertEqual(standings()[-1], ("A", -1, 3))
        self.s.round_action(self.teacher, second, "close")
        self.assertEqual(standings(), [("B", 7, 1), ("A", 5, 2), ("C", 0, 3)])
        self.assertEqual(board()[1]["score"], self.call("partner", "course", course=self.course)["total"])
        self.assertEqual(board(course=self.other), [{"group_name": "A", "rank": 1, "score": 0}])

    def test_group_score_history_and_conflicting_reviews(self):
        self.member("student1", True)
        with self.assertRaises(QuizError):
            self.member("student2", password="incorrect")
        self.member("student2")
        with self.assertRaises(QuizError):
            self.member("student2", True)
        self.member("student2", True, self.other)
        self.assertEqual(len(self.call("student2", "home")["studying"]), 2)
        self.call("helper", "home")
        self.call("teacher", "assistant", course=self.course, uid="helper")
        helper = self.room("helper", aid=self.aid)
        first, second = self.student("student1"), self.student("student2")
        self.s.transition(self.teacher, self.aid, "active")
        self.s.submit(first, self.aid, "1", "原始答案", 2)
        self.s.submit(second, self.aid, "1", "原始答案", 2)
        with self.assertRaises(QuizError):
            self.s.submit(second, self.aid, "1", "更改內容", 2)
        self.s.transition(self.teacher, self.aid, "results")
        answer = self.s.snapshot(helper, self.aid)["answers"][0]
        self.assertEqual(answer["author"], "student1@example.org")
        aid = answer["id"]
        self.s.review(helper, self.aid, aid, "correct", 0)
        with self.assertRaises(QuizError):
            self.s.review(self.teacher, self.aid, aid, "incorrect", 0)
        self.assertEqual(self.call("student2", "course", course=self.course)["total"], 6)
        self.s.review(self.teacher, self.aid, aid, "incorrect", 1)
        self.assertEqual(self.call("student2", "course", course=self.course)["total"], -2)
        self.assertEqual(self.call("student2", "course", course=self.other)["total"], 0)
        saved = self.s.snapshot(self.teacher, self.aid)["answers"][0]
        self.assertEqual([r["uid"] for r in saved["reviews"]], ["helper", "teacher"])
        self.assertEqual(
            self.s.snapshot(self.student("student2"), self.aid)["answers"][0]["text"], "原始答案"
        )
        self.assertNotIn("author", self.s.snapshot(second, self.aid)["answers"][0])

    def test_permission_and_legacy_transfer(self):
        with self.assertRaises(QuizError):
            self.call("student", "grant", uid="student")
        with self.assertRaises(QuizError):
            self.call("student", "create-course", title="其他課")
        with self.assertRaises(QuizError):
            self.call("student", "course", course=self.course, staff=True)
        with self.assertRaises(QuizError):
            self.call("teacher", "claim", aid=self.legacy, course=self.course)
        self.call("admin", "claim", aid=self.legacy, course=self.course)
        self.assertEqual(self.s.snapshot(self.teacher, self.legacy)["title"], "舊活動")
        with self.assertRaises(QuizError):
            self.call("admin", "claim", aid=self.legacy, course=self.other)
        with self.assertRaises(QuizError):
            self.s.snapshot(self.old_token, self.legacy)

    def test_password_reset_is_scoped_and_keeps_history(self):
        self.member("student1", True)
        first = self.student("student1")
        self.s.transition(self.teacher,self.aid,"active")
        self.s.submit(first,self.aid,"1","原始答案",2)
        self.call("helper","home")
        self.call("teacher","assistant",course=self.course,uid="helper")
        tid = self.call("teacher","course",course=self.course,staff=True)["teams"][0]["id"]
        for actor in ("student1", "helper", "admin"):
            with self.assertRaises(QuizError):
                self.call(actor,"reset-password",course=self.course,team=tid,password="new-pass")
        with self.assertRaises(QuizError):
            self.call("teacher","reset-password",course=self.other,team=tid,password="new-pass")
        with self.assertRaises(QuizError):
            self.call("teacher","reset-password",course=self.course,team=tid,password="short")
        self.call("teacher","reset-password",course=self.course,team=tid,password="new-pass")
        with self.assertRaises(QuizError): self.member("student2")
        self.member("student2",password="new-pass")
        self.assertEqual(self.call("student1","home")["studying"][0]["name"],"第一組")
        detail = dict(course=self.course,aid=self.aid)
        self.assertEqual(self.call("student2","history-detail",**detail)["answers"][0]["verdict"],"withheld")
        self.call("another","create-team",course=self.course,name="別組",password="team-pass")
        self.student("another")
        self.assertEqual(self.call("another","history-detail",**detail)["answers"],[])
        with self.assertRaises(QuizError): self.call("student1","history-detail",staff=True,**detail)
        with self.assertRaises(QuizError): self.call("teacher","history-detail",course=self.other,aid=self.aid,staff=True)
        self.s.transition(self.teacher,self.aid,"results")
        row=self.call("helper","history-detail",staff=True,**detail)["answers"][0]
        self.s.review(self.teacher,self.aid,row["id"],"correct",0)
        self.assertEqual(self.call("student1","history-detail",**detail)["answers"][0]["text"],"原始答案")
        self.assertEqual(self.call("student1","course",course=self.course)["total"],6)
        self.assertEqual(self.call("helper","history-detail",staff=True,**detail)["answers"][0]["reviews"][0]["uid"],"teacher")

    def test_membership_after_restart_and_legacy_downgrade(self):
        self.member("returning", True)
        with tempfile.TemporaryDirectory() as folder:
            service = QuizService(Path(folder) / "course.db", "test")
            self.s.db.backup(service.db)
            service.close()
            service = QuizService(Path(folder) / "course.db", "test")
            try:
                with self.assertRaises(ValueError):
                    make_server(service, 0)
                accounts = Courses(service, self.accounts.config, "admin", self.accounts.verify)
                self.assertEqual(accounts.dispatch("returning", "home", {})["studying"][0]["id"], self.course)
                with self.assertRaises(ValueError):
                    Courses(service, {"projectId": "another"}, "admin")
            finally:
                service.close()

    def test_http_scope_and_role(self):
        self.call("ta", "home")
        self.call("teacher", "assistant", course=self.course, uid="ta")
        helper = self.room("ta", aid=self.aid)
        foreign = self.call("teacher", "staff-room", course=self.other)["token"]
        server = make_server(self.s, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(token, path, data=None):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request(
                "GET" if data is None else "POST",
                path,
                body=json.dumps(data) if data is not None else None,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            response = conn.getresponse()
            response.read()
            conn.close()
            return response.status

        path = "/api/activities/" + self.aid
        self.assertEqual(request(helper, path), 200)
        self.assertEqual(request(helper, path + "/start", {}), 403)
        self.assertEqual(request(helper, path + "/reference", {}), 403)
        self.assertEqual(request(helper, "/api/activities", {}), 403)
        self.assertEqual(request(helper, "/api/account/create-course", {"title": "假冒"}), 403)
        self.assertEqual(request(foreign, path), 403)
        self.assertEqual(request(foreign, path + "/end", {}), 403)
        self.assertEqual(request(self.old_token, "/api/activities"), 401)
        self.assertEqual(request("", "/api/join", {}), 403)


class FirebaseIdentityTests(unittest.TestCase):
    def test_signed_token_and_claims(self):
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from google.auth import crypt, jwt
        except ImportError:
            self.skipTest("需先安裝 requirements-firebase.txt")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "local test")])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(1)
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        fetch = Mock(return_value=SimpleNamespace(status=200, data=json.dumps({"test": pem}).encode()))
        signer = crypt.RSASigner(key, "test")
        claims = {
            "iss": "https://securetoken.google.com/demo",
            "aud": "demo",
            "sub": "student",
            "email": "student@example.org",
            "email_verified": True,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "firebase": {"sign_in_provider": "google.com"},
        }
        with patch("google.auth.transport.requests.Request", return_value=fetch):
            token = jwt.encode(signer, claims).decode()
            self.assertEqual(firebase_identity(token, "demo"), ("student", "student@example.org"))
            for overrides in (
                {"iss": "another"},
                {"aud": "another"},
                {"exp": 0},
                {"email_verified": False},
                {"firebase": {"sign_in_provider": "password"}},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(QuizError):
                    firebase_identity(jwt.encode(signer, {**claims, **overrides}).decode(), "demo")
            with self.assertRaises(QuizError):
                firebase_identity(token.rsplit(".", 1)[0] + ".AA", "demo")
