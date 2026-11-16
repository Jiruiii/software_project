import csv
import io
import unittest
import threading
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from app import make_server
from quiz_service import QuizError, QuizService


class ExtraTests(unittest.TestCase):
    def setUp(self):
        self.s = QuizService(":memory:", "extra-test-password")
        self.t = self.s.login("extra-test-password")["token"]
        self.a = self.s.create(self.t, "額外功能", ["1", "2", "3", "4"])
        self.aid = self.a["id"]
        self.u = self.s.join(self.a["code"], "A")["token"]
        self.v = self.s.join(self.a["code"], "B")["token"]

    def tearDown(self):
        self.s.close()

    def test_e01_csv_permissions_order_and_literal_text(self):
        with self.assertRaises(QuizError): self.s.activity_csv(self.u, self.aid)
        with self.assertRaises(QuizError): self.s.activity_csv(self.t, self.aid)
        self.s.transition(self.t, self.aid, "active")
        self.s.submit(self.v, self.aid, "1", '=SUM(1,2)\n"中文"')
        self.s.submit(self.u, self.aid, "1", "second")
        self.s.transition(self.t, self.aid, "results")
        raw = self.s.activity_csv(self.t, self.aid)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual("B", rows[1][2])
        self.assertEqual('\'=SUM(1,2)\n"中文"', rows[1][3])
        self.assertEqual(["1", "是"], rows[1][-2:])
        self.assertEqual(["2", "否"], rows[2][-2:])
        self.assertEqual("無人作答", rows[3][3])

    def test_e01_http_download(self):
        server = make_server(self.s, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/activities/{self.aid}/csv"
        try:
            with self.assertRaises(HTTPError) as denied:
                urlopen(Request(url, headers={"Authorization":"Bearer " + self.u}))
            self.assertEqual(403, denied.exception.code); denied.exception.close()
            self.s.transition(self.t, self.aid, "active"); self.s.transition(self.t, self.aid, "results")
            with urlopen(Request(url, headers={"Authorization":"Bearer " + self.t})) as response:
                self.assertIn("attachment", response.headers["Content-Disposition"])
                self.assertIn("text/csv", response.headers["Content-Type"])
                self.assertIn("無人作答", response.read().decode("utf-8-sig"))
        finally:
            server.shutdown(); thread.join(); server.server_close()

    def test_e02_three_misses_priority_and_new_joiner(self):
        self.s.configure(self.t, self.aid, "sequential", True)
        with patch("quiz_extras.time.time", return_value=100):
            self.s.transition(self.t, self.aid, "active")
            for q in ("1", "2", "3"):
                self.s.submit(self.u, self.aid, q, "first")
                with self.assertRaises(QuizError): self.s.round_action(self.t, self.aid, "next")
                self.s.round_action(self.t, self.aid, "close")
                self.s.round_action(self.t, self.aid, "close")
                self.s.round_action(self.t, self.aid, "next")
            state = self.s.snapshot(self.v, self.aid)
            self.assertTrue(state["round"]["own_priority"])
            self.assertEqual(["4"], state["available_questions"])
            self.assertNotIn("eligible_json", str(state))
            late = self.s.join(self.a["code"], "new")["token"]
            for student in (self.u, late):
                with self.assertRaisesRegex(QuizError, "先答"): self.s.submit(student, self.aid, "4", "early")
            self.s.submit(self.v, self.aid, "4", "priority")
        with patch("quiz_extras.time.time", return_value=103):
            self.s.submit(self.u, self.aid, "4", "later")
            self.s.round_action(self.t, self.aid, "close")
            self.assertEqual("results", self.s.snapshot(self.t, self.aid)["phase"])

    def test_e02_settings_stage_and_round_gate(self):
        with self.assertRaises(QuizError): self.s.configure(self.u, self.aid, "sequential", True)
        with self.assertRaises(QuizError): self.s.configure(self.t, self.aid, "all", True)
        self.s.configure(self.t, self.aid, "sequential")
        self.s.transition(self.t, self.aid, "active")
        with self.assertRaises(QuizError): self.s.configure(self.t, self.aid, "all")
        with self.assertRaises(QuizError): self.s.submit(self.u, self.aid, "2", "future")
        self.s.round_action(self.t, self.aid, "close")
        with self.assertRaises(QuizError): self.s.submit(self.u, self.aid, "1", "closed")

    def test_e04_stake_validation_and_immutable_retry(self):
        self.s.transition(self.t, self.aid, "active")
        for invalid in (0, 4, -1, True, 1.0, "2", None):
            with self.assertRaises(QuizError): self.s.submit(self.u, self.aid, "1", "answer", invalid)
        answer = self.s.submit(self.u, self.aid, "1", "answer", 3)
        self.assertEqual(3, answer["stake"])
        self.assertEqual(answer, self.s.submit(self.u, self.aid, "1", "answer", 3))
        with self.assertRaises(QuizError): self.s.submit(self.u, self.aid, "1", "answer", 2)
        self.assertEqual(1, self.s.submit(self.v, self.aid, "1", "default")["stake"])

    def test_e02_existing_database_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"old.sqlite3"
            service = QuizService(path, "password")
            teacher = service.login("password")["token"]
            a = service.create(teacher, "old", ["1"])
            student = service.join(a["code"], "old group")["token"]
            service.transition(teacher, a["id"], "active"); service.submit(student, a["id"], "1", "preserve")
            service.close()
            db = sqlite3.connect(path)
            db.executescript("DROP TABLE question_meta; DROP TABLE group_progress; DROP TABLE activity_options;")
            db.close()
            service = QuizService(path, "password")
            try:
                state = service.snapshot(teacher, a["id"])
                self.assertEqual("preserve", state["answers"][0]["text"])
                self.assertEqual("all", state["settings"]["mode"])
                self.assertEqual([{"id":"1", "questions":["1"]}], state["units"])
            finally: service.close()


if __name__ == "__main__": unittest.main()
