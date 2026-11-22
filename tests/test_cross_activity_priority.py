import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_accounts import Courses
from quiz_service import QuizError, QuizService


class CrossActivityPriorityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "priority.sqlite3"
        clock = patch("quiz_service.time.time", return_value=1000)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.connect()
        self.addCleanup(lambda: self.quiz.close())
        self.call("teacher", "home")
        self.call("admin", "grant", uid="teacher")
        self.course = self.call("teacher", "create-course", title="數學")["course"]
        self.teacher = self.call("teacher", "staff-room", course=self.course)["token"]
        self.source = self.quiz.create(self.teacher, "上週", ["1"])["id"]
        self.activity = self.quiz.create(self.teacher, "本週", ["1", "2a", "2b"])["id"]
        with self.quiz.db:
            self.quiz.db.execute("UPDATE question_meta SET unit_id='2' WHERE activity_id=? AND question_id IN ('2a','2b')", (self.activity,))

    def connect(self):
        self.quiz = QuizService(self.path, "test")
        self.accounts = Courses(self.quiz, {"projectId": "fixture"}, "admin", lambda uid, project: (uid, uid + "@example.org"))

    def call(self, user, action, **data):
        return self.accounts.dispatch(user, action, data)

    def team(self, user, name=None):
        self.call(user, "create-team", course=self.course, name=name or user, password="class123")

    def enter(self, user, aid):
        return self.call(user, "student-room", course=self.course, aid=aid)["token"]

    def finish_source(self):
        self.quiz.transition(self.teacher, self.source, "active")
        self.quiz.transition(self.teacher, self.source, "results")

    def test_source_choices_and_permissions(self):
        other = self.call("teacher", "create-course", title="英文")["course"]
        other_token = self.call("teacher", "staff-room", course=other)["token"]
        foreign = self.quiz.create(other_token, "上週", ["1"])["id"]
        self.quiz.transition(other_token, foreign, "active")
        self.quiz.transition(other_token, foreign, "results")
        self.quiz.transition(self.teacher, self.source, "active")
        for unavailable in (self.source, foreign, self.activity, "unknown", [], ""):
            with self.subTest(source=unavailable), self.assertRaises(QuizError):
                self.quiz.configure(self.teacher, self.activity, "all", priority_source=unavailable)
        self.quiz.transition(self.teacher, self.source, "results")
        self.team("student")
        student = self.enter("student", self.activity)
        self.call("ta", "home")
        self.call("teacher", "assistant", course=self.course, uid="ta")
        assistant = self.call("ta", "staff-room", course=self.course, aid=self.activity)["token"]
        teacher_state = self.quiz.snapshot(self.teacher, self.activity)
        self.assertEqual([self.source], [row["id"] for row in teacher_state["priority_sources"]])
        for token in (student, assistant):
            state = self.quiz.snapshot(token, self.activity)
            self.assertNotIn("priority_sources", state)
            self.assertNotIn("priority_source", state["settings"])
            with self.assertRaises(QuizError):
                self.quiz.configure(token, self.activity, "all", priority_source=self.source)
        with self.assertRaises(QuizError):
            self.quiz.configure(other_token, self.activity, "all", priority_source=foreign)
        with self.assertRaises(QuizError):
            self.quiz.configure(self.teacher, self.activity, "sequential", priority_source=self.source)
        self.quiz.configure(self.teacher, self.activity, "all", priority_source=self.source)
        self.assertEqual(self.source, self.quiz.snapshot(self.teacher, self.activity)["settings"]["priority_source"])
        self.quiz.configure(self.teacher, self.activity, "all", priority_source=None)
        self.quiz.transition(self.teacher, self.activity, "active")
        self.assertEqual(0, self.quiz.snapshot(student, self.activity)["round"]["priority_until"])
        with self.assertRaises(QuizError):
            self.quiz.configure(self.teacher, self.activity, "all", priority_source=self.source)

    def test_ties_identity_absences_regrade_restart_and_boundary(self):
        for name in ("甲", "乙", "丙", "丁", "戊"):
            self.team(name)
        self.quiz.question_settings(self.teacher, self.source, "1", True, [
            {"question": "1", "type": "choice", "options": ["是", "否"], "correct_index": 0}])
        self.quiz.transition(self.teacher, self.source, "active")
        # 丁 has the lowest score in the source, but joins the target late.
        for name, answer, stake in (("甲", "否", 2), ("乙", "否", 2), ("丙", "是", 0), ("丁", "否", 3)):
            self.quiz.submit(self.enter(name, self.source), self.source, "1", answer, stake)
        self.quiz.transition(self.teacher, self.source, "results")
        # A renamed team is entered by another member. A different new team takes its old name.
        with self.quiz.db:
            self.quiz.db.execute("UPDATE teams SET name='甲改名',norm='甲改名' WHERE course=? AND name='甲'", (self.course,))
        self.team("新甲", name="甲")
        self.call("隊友", "join-team", course=self.course, name="甲改名", password="class123")
        tokens = {name: self.enter(name, self.activity) for name in ("隊友", "乙", "丙", "戊", "新甲")}
        self.quiz.configure(self.teacher, self.activity, "all", priority_source=self.source)
        self.clock.return_value = 2000
        self.quiz.transition(self.teacher, self.activity, "active")
        tokens["丁"] = self.enter("丁", self.activity)
        for name, token in tokens.items():
            state = self.quiz.snapshot(token, self.activity)
            self.assertEqual(2003, state["round"]["priority_until"])
            self.assertEqual(name in ("隊友", "乙"), state["round"]["own_priority"])
            self.assertNotIn("eligible_json", state["round"])
            self.assertNotIn("priority_source", state["settings"])
        self.quiz.submit(tokens["隊友"], self.activity, "1", "先答")
        bundle = {"2a": "A", "2b": "B"}
        self.quiz.submit_unit(tokens["乙"], self.activity, "2", bundle)
        answer = next(r for r in self.quiz.snapshot(self.teacher, self.source)["answers"] if r["group_name"] == "乙")
        self.quiz.review(self.teacher, self.source, answer["id"], "correct", answer["review_revision"])
        self.quiz.close()
        self.connect()
        self.clock.return_value = 2002.999
        self.quiz.transition(self.teacher, self.activity, "active")
        self.quiz.submit(tokens["乙"], self.activity, "1", "保留資格")
        for name in ("丙", "戊", "新甲", "丁"):
            token = tokens[name]
            self.assertEqual([], self.quiz.snapshot(token, self.activity)["available_questions"])
            with self.assertRaisesRegex(QuizError, "先答"):
                self.quiz.submit(token, self.activity, "1", "太早")
            with self.assertRaisesRegex(QuizError, "先答"):
                self.quiz.submit_unit(token, self.activity, "2", bundle)
        self.clock.return_value = 2003
        self.assertEqual(["1", "2a", "2b"], self.quiz.snapshot(tokens["新甲"], self.activity)["available_questions"])
        self.assertEqual(3000, self.quiz.submit(tokens["新甲"], self.activity, "1", "到期")["elapsed_ms"])
        self.quiz.submit_unit(tokens["丙"], self.activity, "2", bundle)

    def test_missing_history_and_manual_close(self):
        self.team("舊組")
        self.enter("舊組", self.source)
        self.finish_source()
        self.team("新組")
        new = self.enter("新組", self.activity)
        self.quiz.configure(self.teacher, self.activity, "all", priority_source=self.source)
        self.quiz.transition(self.teacher, self.activity, "active")
        self.assertEqual(0, self.quiz.snapshot(new, self.activity)["round"]["priority_until"])
        self.quiz.submit(new, self.activity, "1", "可答")
        self.quiz.transition(self.teacher, self.activity, "results")
        with self.assertRaises(QuizError):
            self.quiz.submit_unit(new, self.activity, "2", {"2a": "A", "2b": "B"})

    def test_zero_score_and_activity_deadline_during_priority(self):
        self.team("零分組")
        self.enter("零分組", self.source)
        self.finish_source()
        zero = self.enter("零分組", self.activity)
        self.quiz.configure(self.teacher, self.activity, "all", duration_seconds=1, priority_source=self.source)
        self.quiz.transition(self.teacher, self.activity, "active")
        self.assertTrue(self.quiz.snapshot(zero, self.activity)["round"]["own_priority"])
        self.clock.return_value = 1001
        with self.assertRaises(QuizError):
            self.quiz.submit(zero, self.activity, "1", "已逾時")
        self.assertEqual("results", self.quiz.snapshot(zero, self.activity)["phase"])

    def test_regrade_before_start_uses_latest_points_and_manual_end_stops_priority(self):
        self.team("甲")
        self.team("乙")
        self.quiz.transition(self.teacher, self.source, "active")
        self.quiz.submit(self.enter("甲", self.source), self.source, "1", "答案", 2)
        self.enter("乙", self.source)
        self.quiz.transition(self.teacher, self.source, "results")
        first = self.enter("甲", self.activity)
        second = self.enter("乙", self.activity)
        self.quiz.configure(self.teacher, self.activity, "all", priority_source=self.source)
        answer = self.quiz.snapshot(self.teacher, self.source)["answers"][0]
        self.quiz.review(self.teacher, self.source, answer["id"], "correct", answer["review_revision"])
        self.quiz.transition(self.teacher, self.activity, "active")
        self.assertFalse(self.quiz.snapshot(first, self.activity)["round"]["own_priority"])
        self.assertTrue(self.quiz.snapshot(second, self.activity)["round"]["own_priority"])
        self.quiz.transition(self.teacher, self.activity, "results")
        with self.assertRaises(QuizError):
            self.quiz.submit(second, self.activity, "1", "活動已結束")
