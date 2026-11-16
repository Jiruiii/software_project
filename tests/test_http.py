import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app import make_server
from quiz_service import QuizService
from google_sheets import SheetsWorkflow
from test_google_sheets import FakeGoogle, COPY_URL


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.s = QuizService(":memory:", "http-test-password")
        self.server = make_server(self.s, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.s.close()

    def request(self, path, data=None, token=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["Authorization"] = "Bearer " + token
        req = Request(self.base + path, data=None if data is None else json.dumps(data).encode(), headers=h)
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    def test_full_http_lifecycle_and_privacy(self):
        status, login = self.request("/api/teacher/login", {"password": "http-test-password"})
        self.assertEqual(200, status)
        teacher = login["token"]
        status, activity = self.request("/api/activities", {"title": "HTTP", "questions": ["1", "2"]}, teacher)
        self.assertEqual(201, status)
        path = "/api/activities/" + activity["id"]
        _, a = self.request("/api/join", {"code": activity["code"], "group": "A"})
        _, b = self.request("/api/join", {"code": activity["code"], "group": "B"})
        self.assertEqual(401, self.request(path)[0])
        self.assertEqual(403, self.request(path + "/start", {}, a["token"])[0])
        self.assertEqual(409, self.request(path + "/answers", {"question": "1", "answer": "early"}, a["token"])[0])
        self.request(path + "/start", {}, teacher)
        self.request(path + "/answers", {"question": "1", "answer": "first", "group_id": "spoof", "received_at": 99999999999}, b["token"])
        self.request(path + "/answers", {"question": "1", "answer": "second", "received_at": 0}, a["token"])
        _, state = self.request(path, token=a["token"])
        self.assertNotIn("first", json.dumps(state))
        self.assertNotIn("groups", state)
        self.assertNotIn("id", state["answers"][0])
        _, state = self.request(path, token=teacher)
        self.assertEqual(2, len(state["answers"]))
        self.request(path + "/end", {}, teacher)
        _, state = self.request(path, token=a["token"])
        self.assertEqual("B", state["results"][0]["winner"]["group_name"])
        self.assertIsNone(state["results"][1]["winner"])
        self.assertEqual(409, self.request(path + "/answers", {"question": "2", "answer": "late"}, a["token"])[0])

    def test_request_protection(self):
        self.assertEqual(403, self.request("/api/health", headers={"Host": "evil.example"})[0])
        self.assertEqual(403, self.request("/api/join", {}, headers={"Origin": "https://evil.example"})[0])
        self.assertEqual(415, self.request("/api/join", {}, headers={"Content-Type": "text/plain"})[0])
        self.assertEqual(400, self.request("/api/join", [1, 2])[0])
        self.assertEqual(413, self.request("/api/join", {"blob": "x" * 70000})[0])
        self.assertEqual(404, self.request("/../quiz_service.py")[0])

    def test_google_configuration_and_callback_boundary(self):
        _,login=self.request("/api/teacher/login",{"password":"http-test-password"})
        teacher=login["token"]
        status,data=self.request("/api/google/status",token=teacher)
        self.assertEqual(200,status)
        self.assertEqual({"configured","connected"},set(data))
        self.assertEqual(401,self.request("/api/google/status")[0])
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.base+"/oauth/callback?state=invalid&code=synthetic",headers={"Sec-Fetch-Site":"cross-site"}),timeout=3)
        with caught.exception as response:
            self.assertEqual(400,response.status)
            self.assertIn("已失效",response.read().decode())
        with urlopen(self.base+"/google-setup.html",timeout=3) as response:
            self.assertEqual(200,response.status)
            self.assertIn("Desktop app",response.read().decode())


class SheetsHttpTests(HttpTests):
    def setUp(self):
        self.s=QuizService(":memory:","http-test-password")
        self.google=FakeGoogle()
        self.server=make_server(self.s,0,SheetsWorkflow(self.s,self.google))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    # Reuse helpers without repeating unrelated tests from the parent class.
    test_full_http_lifecycle_and_privacy = None
    test_request_protection = None
    test_google_configuration_and_callback_boundary = None

    def test_import_export_routes_and_student_denial(self):
        _,login=self.request("/api/teacher/login",{"password":"http-test-password"}); t=login["token"]
        status,p=self.request("/api/sheets/preview",{"url":COPY_URL},t)
        self.assertEqual(200,status); self.assertEqual(6,p["count"])
        status,a=self.request("/api/sheets/import",{"preview_id":p["preview_id"],"title":"HTTP sheet"},t)
        self.assertEqual(201,status); path="/api/activities/"+a["id"]
        _,student=self.request("/api/join",{"code":a["code"],"group":"A"}); s=student["token"]
        for route,data in [("/api/sheets/preview",{"url":COPY_URL}), ("/api/sheets/import",{}), (path+"/export",{}), ("/api/google/connect",{})]:
            self.assertEqual(403,self.request(route,data,s)[0])
        self.assertNotIn("source",self.request(path,token=s)[1])
        self.assertEqual(409,self.request(path+"/export",{},t)[0])
        self.request(path+"/start",{},t)
        self.request(path+"/answers",{"question":"1","answer":"HTTP answer"},s)
        self.request(path+"/end",{},t)
        status,result=self.request(path+"/export",{},t)
        self.assertEqual(200,status); self.assertEqual(1,result["written"])


if __name__ == "__main__":
    unittest.main()
