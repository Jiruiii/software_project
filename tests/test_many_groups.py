"""Concurrent real-HTTP regression, with an isolated temporary database."""
import concurrent.futures
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from app import make_server
from quiz_service import QuizService


class ManyGroupsTests(unittest.TestCase):
    metrics = []
    groups = 30

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="classroom-concurrency-")
        self.service = QuizService(Path(self.temp.name) / "test.sqlite3", "concurrency-test-only")
        self.server = make_server(self.service, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.latencies = []
        self.teacher = self.ok("/api/teacher/login", {"password":"concurrency-test-only"})["token"]

    def tearDown(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()
        self.service.close(); self.temp.cleanup()

    def request(self, path, data=None, token=None):
        headers = {"Content-Type":"application/json"}
        if token: headers["Authorization"] = "Bearer " + token
        req = Request(self.base + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        start = time.perf_counter()
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            result = response.status, json.loads(response.read())
        self.latencies.append((time.perf_counter()-start)*1000)
        return result

    def ok(self, path, data=None, token=None):
        status, result = self.request(path, data, token)
        self.assertIn(status, (200,201), (path,status,result))
        return result

    def activity(self, title, questions):
        activity = self.ok("/api/activities", {"title":title,"questions":questions}, self.teacher)
        path = "/api/activities/" + activity["id"]
        people = [self.ok("/api/join", {"code":activity["code"],"group":f"測試組{i:02}"})["token"] for i in range(self.groups)]
        self.ok(path+"/start", {}, self.teacher)
        return path, people

    def together(self, jobs):
        gate = threading.Barrier(len(jobs))
        def run(job):
            gate.wait(timeout=10)
            return job()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return list(pool.map(run, jobs))

    def test_30_groups_six_questions_three_rounds(self):
        rounds = []
        for round_no in range(3):
            questions = [str(i) for i in range(1,7)]
            path, people = self.activity(f"併發第 {round_no+1} 輪", questions)
            received = {}
            for q in questions:
                replies = self.together([
                    lambda i=i,t=t,q=q: self.ok(path+"/answers", {
                        "question":q, "answer":f"R{round_no}-G{i:02}-Q{q}",
                        "received_at":-i, "group_id":"cannot-spoof"}, t)
                    for i,t in enumerate(people)])
                for i,reply in enumerate(replies): received[i,q] = reply
            state = self.ok(path, token=self.teacher)
            self.assertEqual(30,len(state["groups"]))
            self.assertEqual(180,len(state["answers"]))
            self.assertEqual(180,len({(a["group_id"],a["question_id"]) for a in state["answers"]}))
            self.assertEqual({f"R{round_no}-G{i:02}-Q{q}" for i in range(30) for q in questions}, {a["text"] for a in state["answers"]})
            for i,t in enumerate(people):
                own = self.ok(path, token=t)
                self.assertNotIn("groups",own); self.assertNotIn("results",own)
                self.assertEqual(6,len(own["answers"]))
                for answer in own["answers"]:
                    self.assertEqual(received[i,answer["question_id"]],answer)
                    self.assertNotIn("id",answer)
            self.ok(path+"/end", {}, self.teacher)
            result = self.ok(path, token=self.teacher)["results"]
            for row in result:
                q = row["question_id"]
                first = min((a for a in state["answers"] if a["question_id"]==q),key=lambda a:a["id"])
                self.assertEqual(first["group_name"],row["winner"]["group_name"])
                self.assertEqual(first["text"],row["winner"]["text"])
                self.assertEqual(min(received[i,q]["received_at"] for i in range(30)),row["winner"]["received_at"])
            for t in people: self.assertEqual(result,self.ok(path,token=t)["results"])
            rounds.append({"round":round_no+1,"answers":180,"winners":[r["winner"]["group_name"] for r in result]})
        ordered = sorted(self.latencies)
        self.metrics.append({"scenario":"30 groups x 6 questions x 3 rounds", "answers":540,
                             "rounds":rounds,"requestP95Ms":round(ordered[int(.95*(len(ordered)-1))],1),
                             "requestMaxMs":round(max(ordered),1)})

    def test_known_first_and_same_group_concurrent_conflicts(self):
        path, people = self.activity("已知第一名及同組衝突", ["1","2","3"])
        first = self.ok(path+"/answers",{"question":"1","answer":"known-first"},people[-1])
        self.together([lambda t=t:self.ok(path+"/answers",{"question":"1","answer":"later","received_at":0},t) for t in people[:-1]])
        replies = self.together([lambda i=i:self.request(path+"/answers",{"question":"2","answer":f"candidate-{i}"},people[0]) for i in range(30)])
        self.assertEqual(1,sum(status==200 for status,_ in replies))
        self.assertEqual(29,sum(status==409 for status,_ in replies))
        accepted = next(reply for status,reply in replies if status==200)
        retries = self.together([lambda:self.ok(path+"/answers",{"question":"2","answer":accepted["text"]},people[0]) for _ in range(30)])
        self.assertTrue(all(reply==accepted for reply in retries))
        self.assertEqual(31,len(self.ok(path,token=self.teacher)["answers"]))
        self.ok(path+"/end",{},self.teacher)
        result = self.ok(path,token=self.teacher)["results"]
        self.assertEqual("測試組29",result[0]["winner"]["group_name"])
        self.assertEqual(first["received_at"],result[0]["winner"]["received_at"])
        self.assertIsNone(result[2]["winner"])
        self.metrics.append({"scenario":"known first / 30 conflicting submissions / 30 identical retries", "conflictsRejected":29,"singleSavedAnswer":True})

    def test_end_races_with_30_groups_and_rejects_late_answers(self):
        path, people = self.activity("結束邊界",["1","2"])
        jobs=[lambda t=t:self.request(path+"/answers",{"question":"1","answer":"race"},t) for t in people]
        jobs.append(lambda:self.request(path+"/end",{},self.teacher))
        replies=self.together(jobs)
        self.assertEqual(200,replies[-1][0])
        self.assertTrue(all(status in (200,409) for status,_ in replies[:-1]))
        ended=self.ok(path,token=self.teacher)
        accepted=sum(status==200 for status,_ in replies[:-1])
        self.assertEqual(accepted,len(ended["answers"]))
        self.assertTrue(all(a["received_at"]<=ended["ended_at"] for a in ended["answers"]))
        late=self.together([lambda t=t:self.request(path+"/answers",{"question":"2","answer":"late"},t) for t in people])
        self.assertTrue(all(status==409 for status,_ in late))
        after=self.ok(path,token=self.teacher)
        # Server clock advances for countdown displays; the stored activity,
        # answers, winners and scores must all remain unchanged.
        self.assertGreaterEqual(after.pop('server_time'),ended.pop('server_time'))
        self.assertEqual(ended,after)
        self.metrics.append({"scenario":"end races with 30 groups", "acceptedBeforeEnd":accepted,"rejectedAfterEnd":30})


if __name__ == "__main__": unittest.main()
