import unittest
from unittest.mock import patch

from quiz_service import QuizError, QuizService


class ActivityChatTests(unittest.TestCase):
    def setUp(self):
        self.s = QuizService(":memory:", "test")
        self.addCleanup(self.s.close)
        self.teacher = self.s.login("test")["token"]

    def room(self, mode="all", duration=0):
        activity = self.s.create(self.teacher, "討論", ["1", "2"])
        self.s.configure(self.teacher, activity["id"], mode, duration_seconds=duration)
        return (activity["id"], *(self.s.join(activity["code"], name)["token"] for name in ("甲組", "乙組")))

    def denied(self, status, operation, *args):
        with self.assertRaises(QuizError) as caught:
            operation(*args)
        self.assertEqual(caught.exception.status, status)

    def assert_closed(self, aid, token):
        self.denied(409, self.s.chat_messages, token, aid, "0")
        self.denied(409, self.s.post_chat, token, aid, "遲到", "late")
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM chat_messages WHERE activity_id=?", (aid,)).fetchone()[0], 0)

    def test_ownership_order_retries_and_manual_close(self):
        aid, a, b = self.room()
        other, outsider, _ = self.room()
        self.assert_closed(aid, a)
        for activity in (aid, other):
            self.s.transition(self.teacher, activity, "active")
        self.s.post_chat(outsider, other, "另一場", "first")
        for token in (self.teacher, outsider):
            self.denied(403, self.s.chat_messages, token, aid, "0")
            self.denied(403, self.s.post_chat, token, aid, "test", "first")
        self.denied(400, self.s.post_chat, a, aid, "  ", "first")
        self.denied(400, self.s.post_chat, a, aid, "a"*501, "first")
        first = self.s.post_chat(a, aid, "第一句", "first")
        self.assertEqual(self.s.post_chat(a, aid, "第一句", "first"), first)
        self.denied(409, self.s.post_chat, a, aid, "已改動", "first")
        second = self.s.post_chat(b, aid, "<b>第二句</b>", "first")
        rows = self.s.chat_messages(b, aid, "0")["messages"]
        self.assertEqual(rows, [
            {**first, "group_name":"甲組", "body":"第一句"},
            {**second, "group_name":"乙組", "body":"<b>第二句</b>"},
        ])
        self.assertEqual(self.s.chat_messages(a, aid, str(first["id"]))["messages"], rows[1:])
        self.s.transition(self.teacher, aid, "results")
        self.assert_closed(aid, a)
        self.assertEqual(self.s.chat_messages(outsider, other, "0")["messages"][0]["body"], "另一場")

    def test_close_only_at_activity_end_and_expire_before_post(self):
        for mode in ("all", "sequential"):
            with self.subTest(mode=mode):
                aid, a, b = self.room(mode, duration=10)
                with patch("quiz_service.time.time", return_value=1000) as clock:
                    self.s.transition(self.teacher, aid, "active")
                    self.s.post_chat(a, aid, "討論中", "1")
                    if mode == "sequential":
                        self.s.round_action(self.teacher, aid, "close")
                        self.s.post_chat(b, aid, "題間發言", "2")
                        self.s.round_action(self.teacher, aid, "next")
                        self.assertEqual(len(self.s.chat_messages(a, aid, "0")["messages"]), 2)
                    clock.return_value = 1011
                    self.denied(409, self.s.post_chat, b, aid, "到期", "3")
                    self.assert_closed(aid, a)
