import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path
from quiz_service import QuizError, QuizService


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "quiz.db"
        self.s = QuizService(self.path, "test-password")
        self.teacher = self.s.login("test-password")["token"]
        self.a = self.s.create(self.teacher, "課堂", ["1", "2", "3"])
        self.student = self.s.join(self.a["code"], "A 組")["token"]

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def err(self, status, fn, *args):
        with self.assertRaises(QuizError) as caught:
            fn(*args)
        self.assertEqual(status, caught.exception.status)

    def start(self):
        self.s.transition(self.teacher, self.a["id"], "active")

    def test_f01_roles_auth_and_logout(self):
        self.err(401, self.s.login, "wrong")
        self.err(403, self.s.create, self.student, "bad", ["1"])
        self.err(403, self.s.transition, self.student, self.a["id"], "active")
        self.err(403, self.s.activities, self.student)
        self.s.logout(self.student)
        self.err(401, self.s.snapshot, self.student, self.a["id"])

    def test_f02_normalized_groups_and_isolation(self):
        second = self.s.join(self.a["code"].lower(), " a 組 ")["token"]
        self.start()
        self.s.submit(self.student, self.a["id"], "1", "共同答案")
        self.assertEqual("共同答案", self.s.snapshot(second, self.a["id"])["answers"][0]["text"])
        other = self.s.create(self.teacher, "別班", ["1"])
        self.err(403, self.s.snapshot, second, other["id"])
        self.err(400, self.s.join, self.a["code"], " ")
        self.err(404, self.s.join, "000000", "A")

    def test_validation_and_atomic_create(self):
        for qs in [[], ["1", "1"], [" "], [1], "1", ["x"] * 101]:
            self.err(400, self.s.create, self.teacher, "title", qs)
        self.err(400, self.s.create, self.teacher, " ", ["1"])
        self.assertEqual(1, len(self.s.activities(self.teacher)))

    def test_f05_f06_f10_phase_gates_and_idempotence(self):
        self.err(409, self.s.submit, self.student, self.a["id"], "1", "x")
        self.err(409, self.s.transition, self.teacher, self.a["id"], "results")
        self.start()
        self.start()
        self.s.submit(self.student, self.a["id"], "1", "x")
        self.s.transition(self.teacher, self.a["id"], "results")
        self.s.transition(self.teacher, self.a["id"], "results")
        self.err(409, self.s.submit, self.student, self.a["id"], "2", "late")
        self.err(409, self.s.transition, self.teacher, self.a["id"], "active")

    def test_f11_first_answer_immutable(self):
        self.start()
        self.err(400, self.s.submit, self.student, self.a["id"], "1", "  ")
        self.err(400, self.s.submit, self.student, self.a["id"], "1", "x" * 2001)
        self.err(404, self.s.submit, self.student, self.a["id"], "missing", "x")
        first = self.s.submit(self.student, self.a["id"], "1", " answer ")
        self.assertEqual(first, self.s.submit(self.student, self.a["id"], "1", "answer"))
        self.err(409, self.s.submit, self.student, self.a["id"], "1", "changed")

    def test_f07_f08_f12_f13_privacy_and_results(self):
        other = self.s.join(self.a["code"], "SECRET_GROUP")["token"]
        self.start()
        self.s.submit(other, self.a["id"], "1", "SECRET_ANSWER")
        own = self.s.submit(self.student, self.a["id"], "2", "own")
        self.assertNotIn("id", own)
        snapshot = self.s.snapshot(self.student, self.a["id"])
        encoded = json.dumps(snapshot)
        self.assertNotIn("SECRET", encoded)
        self.assertNotIn("groups", snapshot)
        self.assertNotIn("results", snapshot)
        teacher = self.s.snapshot(self.teacher, self.a["id"])
        self.assertEqual(2, len(teacher["groups"]))
        self.assertEqual(2, len(teacher["answers"]))
        self.assertIn("received_at", teacher["answers"][0])
        self.s.transition(self.teacher, self.a["id"], "results")
        result = self.s.snapshot(self.student, self.a["id"])["results"]
        self.assertEqual("SECRET_GROUP", result[0]["winner"]["group_name"])
        self.assertIsNone(result[2]["winner"])

    def test_f14_concurrent_groups_and_same_group(self):
        tokens = [self.s.join(self.a["code"], f"組{i}")["token"] for i in range(20)]
        self.start()
        with concurrent.futures.ThreadPoolExecutor(20) as pool:
            list(pool.map(lambda t: self.s.submit(t, self.a["id"], "1", "answer"), tokens))
            list(pool.map(lambda _: self.s.submit(self.student, self.a["id"], "2", "same"), range(20)))
        teacher = self.s.snapshot(self.teacher, self.a["id"])
        self.assertEqual(21, len(teacher["answers"]))
        first = teacher["answers"][0]
        self.s.transition(self.teacher, self.a["id"], "results")
        result = self.s.snapshot(self.student, self.a["id"])["results"]
        self.assertEqual(first["group_name"], result[0]["winner"]["group_name"])

    def test_end_race_has_no_answers_after_end(self):
        self.start()
        def attempt(i):
            try:
                if i == 0:
                    return self.s.transition(self.teacher, self.a["id"], "results")
                return self.s.submit(self.student, self.a["id"], str(i), "answer")
            except QuizError as exc:
                self.assertEqual(409, exc.status)
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            list(pool.map(attempt, range(4)))
        snap = self.s.snapshot(self.teacher, self.a["id"])
        for answer in snap["answers"]:
            self.assertLessEqual(answer["received_at"], snap["ended_at"])

    def test_persistence_and_session_expiration(self):
        self.start()
        self.s.submit(self.student, self.a["id"], "1", "saved")
        self.s.close()
        self.s = QuizService(self.path, "test-password")
        self.assertEqual("saved", self.s.snapshot(self.student, self.a["id"])["answers"][0]["text"])
        with self.s.db:
            self.s.db.execute("UPDATE sessions SET expires_at=0")
        self.err(401, self.s.snapshot, self.student, self.a["id"])


if __name__ == "__main__":
    unittest.main()
