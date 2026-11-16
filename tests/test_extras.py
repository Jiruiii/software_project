import csv
import io
import unittest
import threading
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


if __name__ == "__main__": unittest.main()
