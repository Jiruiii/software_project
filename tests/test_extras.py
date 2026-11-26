import csv
import io
import unittest
import threading
import tempfile
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from app import make_server
from quiz_service import QuizError, QuizService
from guided_notes import from_xlsx, parse_grid


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
        self.assertEqual(["1", "是"], rows[1][7:9])
        self.assertEqual(["2", "否"], rows[2][7:9])
        self.assertEqual(["押注分","搶答分","單位合計"], rows[0][-3:])
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

    def test_e02_lowest_and_time_boundary(self):
        self.s.configure(self.t,self.aid,'sequential',True)
        with patch('quiz_extras.time.time',return_value=100) as clock:
            self.s.transition(self.t,self.aid,'active')
            for token in (self.u,self.v):
                self.assertTrue(self.s.snapshot(token,self.aid)['round']['own_priority'])
            self.s.submit(self.u,self.aid,'1','A',3)
            self.s.round_action(self.t,self.aid,'close')
            row=self.s.snapshot(self.t,self.aid)['answers'][0]
            self.s.review(self.t,self.aid,row['id'],'incorrect')
            self.s.round_action(self.t,self.aid,'next')
            self.assertTrue(self.s.snapshot(self.u,self.aid)['round']['own_priority'])
            late=self.s.join(self.a['code'],'C')['token']
            clock.return_value=102.999
            for token in (self.v,late):
                self.assertEqual([],self.s.snapshot(token,self.aid)['available_questions'])
                with self.assertRaisesRegex(QuizError,'先答'): self.s.submit(token,self.aid,'2','early')
            self.s.submit(self.u,self.aid,'2','priority')
            clock.return_value=103
            self.s.submit(self.v,self.aid,'2','normal')
            self.s.submit(late,self.aid,'2','normal')

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
        for invalid in (4, -1, True, 1.0, "2", None):
            with self.assertRaises(QuizError): self.s.submit(self.u, self.aid, "1", "answer", invalid)
        answer = self.s.submit(self.u, self.aid, "1", "answer", 3)
        self.assertEqual(3, answer["stake"])
        self.assertEqual(answer, self.s.submit(self.u, self.aid, "1", "answer", 3))
        with self.assertRaises(QuizError): self.s.submit(self.u, self.aid, "1", "answer", 2)
        self.assertEqual(0, self.s.submit(self.v, self.aid, "1", "default")["stake"])

    def test_e05_review_replacement_reversal_and_permissions(self):
        self.s.transition(self.t, self.aid, "active")
        self.s.submit(self.u, self.aid, "1", "first", 3)
        self.s.submit(self.v, self.aid, "1", "second", 2)
        ids = [a["id"] for a in self.s.snapshot(self.t, self.aid)["answers"]]
        with self.assertRaises(QuizError): self.s.review(self.t, self.aid, ids[0], "incorrect")
        self.s.transition(self.t, self.aid, "results")
        with self.assertRaises(QuizError): self.s.review(self.u, self.aid, ids[0], "incorrect")
        with self.assertRaises(QuizError): self.s.review(self.t, self.aid, ids[0], "invalid")
        self.s.review(self.t, self.aid, ids[1], "correct")
        waiting = self.s.snapshot(self.u, self.aid)["results"][0]
        self.assertEqual({"question_id":"1", "winner":None, "status":"pending"}, waiting)
        self.s.review(self.t, self.aid, ids[0], "incorrect")
        self.assertEqual("B", self.s.snapshot(self.u, self.aid)["results"][0]["winner"]["group_name"])
        self.s.review(self.t, self.aid, ids[1], "incorrect")
        self.assertIsNone(self.s.snapshot(self.u, self.aid)["results"][0]["winner"])
        self.s.review(self.t, self.aid, ids[0], "pending")
        self.assertEqual("pending", self.s.snapshot(self.u, self.aid)["results"][0]["status"])
        for verdict in ("correct", "correct"):
            self.s.review(self.t, self.aid, ids[0], verdict)
            winner = self.s.snapshot(self.u, self.aid)["results"][0]["winner"]
            self.assertEqual({"group_name":"A"}, winner)

    def test_e06_clusters_unicode_similarity_and_isolation(self):
        self.s.transition(self.t, self.aid, "active")
        self.s.submit(self.u, self.aid, "1", "ＡＢＣ   def")
        self.s.submit(self.v, self.aid, "1", "abc def")
        other = self.s.join(self.a["code"], "C")["token"]
        self.s.submit(other, self.aid, "1", "abc def!")
        before = self.s.snapshot(self.t, self.aid)["answers"]
        result = self.s.clusters(self.t, self.aid, "1")
        self.assertEqual(1, len(result["clusters"]))
        self.assertEqual(3, len(result["clusters"][0]["answers"]))
        self.assertEqual("ＡＢＣ   def", result["clusters"][0]["answers"][0]["text"])
        self.assertEqual(before, self.s.snapshot(self.t, self.aid)["answers"])
        with self.assertRaises(QuizError): self.s.clusters(self.u, self.aid, "1")
        with self.assertRaises(QuizError): self.s.clusters(self.t, self.aid, "unknown")

    def test_e07_private_report_references_and_score(self):
        with self.assertRaises(QuizError): self.s.report_csv(self.u,self.aid)
        self.s.reference(self.t,self.aid,"1","reference")
        self.assertEqual({}, self.s.snapshot(self.u,self.aid)["references"])
        self.s.transition(self.t, self.aid, "active")
        self.s.submit(self.u, self.aid, "1", "own answer", 3)
        self.s.submit(self.v, self.aid, "1", "other secret", 2)
        self.s.transition(self.t, self.aid, "results")
        answer = self.s.snapshot(self.t, self.aid)["answers"][0]
        self.s.review(self.t, self.aid, answer["id"], "incorrect")
        self.s.reference(self.t, self.aid, "1", "=reference")
        report = self.s.snapshot(self.u, self.aid)["report"]
        self.assertEqual(-3, report[0]["points"])
        self.assertEqual("=reference", report[0]["reference"])
        self.assertEqual("unanswered", report[1]["verdict"])
        raw = self.s.report_csv(self.u, self.aid).decode("utf-8-sig")
        self.assertIn("own answer", raw); self.assertNotIn("other secret", raw); self.assertIn("'=reference", raw)
        with self.assertRaises(QuizError): self.s.reference(self.u, self.aid, "1", "bad")
        other = self.s.create(self.t, "other", ["1"])
        with self.assertRaises(QuizError): self.s.report_csv(self.u, other["id"])
        self.s.reference(self.t, self.aid, "1", "")
        self.assertEqual("", self.s.snapshot(self.u, self.aid)["report"][0]["reference"])

    def test_e09_atomic_bundle_concurrency_and_winner(self):
        source = parse_grid(from_xlsx((Path(__file__).parent/'fixtures/grouped.xlsx').read_bytes())[0])
        source['spreadsheet_id']='test-copy-grouped-id-1234'
        a=self.s.create_from_source(self.t,'grouped',source); aid=a['id']
        students=[self.s.join(a['code'],str(i))['token'] for i in range(20)]
        self.s.transition(self.t,aid,'active')
        with self.assertRaises(QuizError): self.s.submit(students[0],aid,'1.1','bypass')
        for data in ({'1.1':'partial'},{'1.1':'ok','1.2':''},{'1.1':'ok','1.2':'ok','3':'extra'}):
            with self.assertRaises(QuizError): self.s.submit_unit(students[0],aid,'1',data)
        self.assertEqual([],self.s.snapshot(self.t,aid)['answers'])
        def send(pair):
            i,token=pair
            return self.s.submit_unit(token,aid,'1',{'1.1':f'A{i}','1.2':f'B{i}'},3)
        with ThreadPoolExecutor(max_workers=20) as pool: list(pool.map(send,enumerate(students)))
        before=self.s.snapshot(self.t,aid)['answers']
        for i in range(0,40,2):
            self.assertEqual(before[i]['group_id'],before[i+1]['group_id'])
            self.assertEqual(before[i]['received_at'],before[i+1]['received_at'])
        send((0,students[0])); self.assertEqual(40,len(self.s.snapshot(self.t,aid)['answers']))
        self.s.transition(self.t,aid,'results')
        self.s.review(self.t,aid,before[0]['id'],'incorrect')
        winners=self.s.snapshot(self.t,aid)['results'][:2]
        self.assertEqual(before[2]['group_name'],winners[0]['winner']['group_name'])
        self.assertEqual(winners[0]['winner']['group_name'],winners[1]['winner']['group_name'])
        source,written=self.s.export_context(self.t,aid)
        self.assertEqual(f"{before[2]['text']}（{before[2]['group_name']}）",written['1.1'])
        self.assertEqual(f"{before[3]['text']}（{before[3]['group_name']}）",written['1.2'])
        def published():
            return self.s.snapshot(students[0],aid)['results'][:2]
        for answer in before[2:4]:
            self.s.review(self.t,aid,answer['id'],'correct')
        self.assertEqual([{'group_name':before[2]['group_name']}] * 2, [r['winner'] for r in published()])
        restored=self.s.review(self.t,aid,before[0]['id'],'correct')
        self.assertEqual(['pending','pending'],[r['status'] for r in published()])
        self.s.review(self.t,aid,before[1]['id'],'correct')
        self.assertEqual([{'group_name':before[0]['group_name']}] * 2, [r['winner'] for r in published()])
        self.s.undo_review_batch(self.t,aid,restored['batch_id'])
        self.assertEqual([{'group_name':before[2]['group_name']}] * 2, [r['winner'] for r in published()])

    def test_e10_scores_ties_negative_and_regrade(self):
        self.s.join(self.a['code'],'C')
        self.s.transition(self.t,self.aid,'active')
        self.s.submit(self.u,self.aid,'1','A',3); self.s.submit(self.v,self.aid,'1','B',3)
        self.assertNotIn('scoreboard',self.s.snapshot(self.u,self.aid))
        self.s.transition(self.t,self.aid,'results')
        state=self.s.snapshot(self.t,self.aid); ids=[a['id'] for a in state['answers']]
        self.assertEqual([1,1,1],[r['rank'] for r in state['scoreboard']])
        for aid in ids: self.s.review(self.t,self.aid,aid,'correct')
        state=self.s.snapshot(self.v,self.aid)
        self.assertEqual([7,5,0],[r['score'] for r in state['scoreboard']])
        self.assertEqual([1,2,3],[r['rank'] for r in state['scoreboard']])
        self.s.review(self.t,self.aid,ids[0],'incorrect'); self.s.review(self.t,self.aid,ids[0],'incorrect')
        self.assertEqual([7,0,-3],[r['score'] for r in self.s.snapshot(self.u,self.aid)['scoreboard']])

    def test_e11_deadline_boundary_and_sequential_expiry(self):
        for invalid in (-1,3601,True,1.5,'3',None):
            with self.assertRaises(QuizError): self.s.configure(self.t,self.aid,'all',False,invalid)
        self.s.configure(self.t,self.aid,'all',False,10)
        with patch('quiz_extras.time.time',return_value=100): self.s.transition(self.t,self.aid,'active')
        with patch('quiz_extras.time.time',return_value=109.999): self.s.submit(self.u,self.aid,'1','before')
        with patch('quiz_extras.time.time',return_value=110):
            with self.assertRaises(QuizError): self.s.submit(self.v,self.aid,'1','late')
            self.assertEqual('results',self.s._activity(self.aid)['phase'])
            self.assertEqual(1,len(self.s.snapshot(self.t,self.aid)['answers']))
        a=self.s.create(self.t,'timed rounds',['1','2'])
        self.s.configure(self.t,a['id'],'sequential',False,5)
        with patch('quiz_extras.time.time',return_value=200): self.s.transition(self.t,a['id'],'active')
        with patch('quiz_extras.time.time',return_value=205):
            state=self.s.snapshot(self.t,a['id']); self.assertEqual('active',state['phase']); self.assertFalse(state['round']['round_open'])
            self.s.round_action(self.t,a['id'],'next')
        with patch('quiz_extras.time.time',return_value=210):
            self.s.tick(); self.assertEqual('results',self.s._activity(a['id'])['phase'])

    def test_e11_background_without_browser_and_restart(self):
        self.s.configure(self.t,self.aid,'all',False,1)
        self.s.transition(self.t,self.aid,'active')
        server=make_server(self.s,0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            time.sleep(1.7)
            with self.s.lock: self.assertEqual('results',self.s._activity(self.aid)['phase'])
        finally: server.shutdown(); thread.join(); server.server_close()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'restart.sqlite3'; s=QuizService(path,'password')
            t=s.login('password')['token']; a=s.create(t,'restart',['1']); s.configure(t,a['id'],'all',False,10)
            with patch('quiz_extras.time.time',return_value=100): s.transition(t,a['id'],'active')
            s.close(); s=QuizService(path,'password')
            try:
                self.assertEqual(110,s._options(a['id'])['deadline'])
                with patch('quiz_extras.time.time',return_value=111): self.assertEqual('results',s.snapshot(t,a['id'])['phase'])
            finally: s.close()

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
            db.executescript("DROP TABLE question_meta; DROP TABLE activity_options; ALTER TABLE answers DROP COLUMN stake; ALTER TABLE answers DROP COLUMN verdict;")
            db.close()
            service = QuizService(path, "password")
            try:
                state = service.snapshot(teacher, a["id"])
                self.assertEqual("preserve", state["answers"][0]["text"])
                self.assertEqual(1, state['answers'][0]['stake'])
                self.assertEqual('pending', state['answers'][0]['verdict'])
                self.assertEqual("all", state["settings"]["mode"])
                self.assertEqual([{"id":"1", "questions":["1"]}], state["units"])
            finally: service.close()


if __name__ == "__main__": unittest.main()
