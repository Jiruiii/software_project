import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import make_server
from quiz_service import QuizError, QuizService


class BatchReviewTests(unittest.TestCase):
    def setUp(self):
        self.s = QuizService(':memory:', 'test')
        self.t = self.s.login('test')['token']
        self.a = self.s.create(self.t, '批次批改', ['1', '2'])
        self.aid = self.a['id']
        self.students = [self.s.join(self.a['code'], name)['token'] for name in ['A', 'B', 'C']]
        self.s.transition(self.t, self.aid, 'active')
        for token, answer, stake in zip(self.students, ['地球是圓的', '地球是圓的', '地球不是圓的'], [1, 2, 3]):
            self.s.submit(token, self.aid, '1', answer, stake)
        self.s.transition(self.t, self.aid, 'results')

    def tearDown(self):
        self.s.close()

    def selections(self):
        answers = self.s.snapshot(self.t, self.aid)['answers']
        return [{'id':a['id'], 'revision':a['review_revision']} for a in answers if a['question_id'] == '1']

    def verdicts(self):
        return [a['verdict'] for a in self.s.snapshot(self.t, self.aid)['answers']]

    def scores(self):
        return [self.s.snapshot(t, self.aid)['own_score']['total'] for t in self.students]

    def test_subset_and_undo_restore_mixed_verdicts_scores(self):
        selected = self.selections()
        self.s.review(self.t, self.aid, selected[0]['id'], 'correct')
        self.s.review(self.t, self.aid, selected[1]['id'], 'incorrect')
        before = self.verdicts(), self.scores()
        result = self.s.review_batch(self.t, self.aid, '1', self.selections(), 'correct')
        self.assertEqual([1, 2, 3], self.scores())
        self.s.undo_review_batch(self.t, self.aid, result['batch_id'])
        self.assertEqual(before, (self.verdicts(), self.scores()))
        with self.assertRaises(QuizError): self.s.undo_review_batch(self.t, self.aid, result['batch_id'])
        self.s.review_batch(self.t, self.aid, '1', self.selections()[:1], 'incorrect')
        self.assertEqual(['incorrect', 'incorrect', 'pending'], self.verdicts())

    def test_invalid_and_stale_batches_are_atomic(self):
        selected = self.selections()
        for bad in [None, [], [selected[0], selected[0]], [selected[0], {'id':9999, 'revision':0}],
                    [{'id':True, 'revision':0}], [{'id':1, 'revision':False}], selected * 334]:
            with self.assertRaises(QuizError): self.s.review_batch(self.t, self.aid, '1', bad, 'correct')
            self.assertEqual(['pending'] * 3, self.verdicts())
        with self.assertRaises(QuizError): self.s.review_batch(self.t, self.aid, '2', selected, 'correct')
        self.s.review(self.t, self.aid, selected[-1]['id'], 'incorrect')
        with self.assertRaises(QuizError): self.s.review_batch(self.t, self.aid, '1', selected, 'correct')
        self.assertEqual(['pending', 'pending', 'incorrect'], self.verdicts())

    def test_authorization_activity_and_phase(self):
        selected = self.selections()
        with self.assertRaises(QuizError): self.s.review_batch(self.students[0], self.aid, '1', selected, 'correct')
        other = self.s.create(self.t, '其他活動', ['1'])['id']
        self.s.transition(self.t, other, 'active'); self.s.transition(self.t, other, 'results')
        with self.assertRaises(QuizError): self.s.review_batch(self.t, other, '1', selected, 'correct')
        self.s.db.execute("UPDATE activities SET phase='active' WHERE id=?", (self.aid,)); self.s.db.commit()
        with self.assertRaises(QuizError): self.s.review_batch(self.t, self.aid, '1', selected, 'correct')
        self.s.db.execute("UPDATE activity_options SET mode='sequential',round_index=0,round_open=0 WHERE activity_id=?", (self.aid,)); self.s.db.commit()
        result = self.s.review_batch(self.t, self.aid, '1', selected, 'correct')
        other_teacher = self.s.login('test')['token']
        for token, aid in [(self.students[0], self.aid), (other_teacher, self.aid), (self.t, other)]:
            with self.assertRaises(QuizError): self.s.undo_review_batch(token, aid, result['batch_id'])
        self.assertEqual(['correct'] * 3, self.verdicts())

    def test_undo_conflicts_even_if_verdict_changed_back(self):
        selected = self.selections()
        result = self.s.review_batch(self.t, self.aid, '1', selected, 'correct')
        self.s.review(self.t, self.aid, selected[-1]['id'], 'incorrect')
        self.s.review(self.t, self.aid, selected[-1]['id'], 'correct')
        with self.assertRaises(QuizError): self.s.undo_review_batch(self.t, self.aid, result['batch_id'])
        self.assertEqual(['correct'] * 3, self.verdicts())

    def test_concurrent_batches_only_one_succeeds(self):
        selected = self.selections()
        def run(verdict):
            try:
                self.s.review_batch(self.t, self.aid, '1', selected, verdict)
                return 200
            except QuizError as e: return e.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([200, 409], sorted(pool.map(run, ['correct', 'incorrect'])))
        self.assertEqual(1, len(set(self.verdicts())))

    def test_grouped_scores_and_export_invalidation(self):
        self.s.db.execute("UPDATE activities SET phase='active' WHERE id=?", (self.aid,)); self.s.db.commit()
        for token, stake in zip(self.students, [1, 2, 3]):
            self.s.submit(token, self.aid, '2', 'child', stake)
        self.s.db.execute("UPDATE question_meta SET unit_id='1' WHERE activity_id=?", (self.aid,)); self.s.db.commit()
        self.s.transition(self.t, self.aid, 'results')
        for a in self.s.snapshot(self.t, self.aid)['answers']:
            if a['question_id'] == '2': self.s.review(self.t, self.aid, a['id'], 'correct')
        self.s.db.execute("INSERT INTO sheet_sources(activity_id,source_json,exported_at) VALUES(?,?,?)",
                          (self.aid, json.dumps({'sheet_title':'test', 'spreadsheet_id':'test',
                              'targets':[{'question':'1', 'original':''}, {'question':'2', 'original':''}],
                              'last_export':{'1':'地球是圓的', '2':'child'}}), 123)); self.s.db.commit()
        result = self.s.review_batch(self.t, self.aid, '1', self.selections(), 'incorrect')
        self.assertEqual([-1, -2, -3], self.scores())
        self.assertIsNone(self.s.db.execute('SELECT exported_at FROM sheet_sources').fetchone()[0])
        self.s.undo_review_batch(self.t, self.aid, result['batch_id'])
        self.assertEqual([0, 0, 0], self.scores())

    def test_http_routes_and_cluster_metadata(self):
        server = make_server(self.s, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def post(action, data, token=self.t):
            request = Request(f'http://127.0.0.1:{server.server_port}/api/activities/{self.aid}/{action}',
                              data=json.dumps(data).encode(), headers={'Content-Type':'application/json', 'Authorization':'Bearer '+token})
            try: response = urlopen(request, timeout=3)
            except HTTPError as e: response = e
            with response: return response.status, json.loads(response.read())
        try:
            status, clusters = post('clusters', {'question':'1'})
            self.assertEqual(200, status)
            self.assertTrue(clusters['reviewable'])
            self.assertFalse(clusters['clusters'][0]['exact'])
            self.assertIn('review_revision', clusters['clusters'][0]['answers'][0])
            status, result = post('review-batch', {'question':'1', 'selections':self.selections(), 'verdict':'correct'})
            self.assertEqual(200, status)
            self.assertEqual(403, post('review-undo', {'batch_id':result['batch_id']}, self.students[0])[0])
            self.assertEqual(200, post('review-undo', {'batch_id':result['batch_id']})[0])
        finally:
            server.shutdown(); thread.join(); server.server_close()

    def test_legacy_database_migration_and_persistent_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'legacy.sqlite3'
            service = QuizService(db, 'test')
            teacher = service.login('test')['token']
            activity = service.create(teacher, 'existing', ['1'])
            student = service.join(activity['code'], 'A')['token']
            service.transition(teacher, activity['id'], 'active')
            service.submit(student, activity['id'], '1', 'old answer', 2)
            service.transition(teacher, activity['id'], 'results')
            service.db.execute('ALTER TABLE answers DROP COLUMN review_revision')
            service.db.execute('DROP TABLE review_batches'); service.db.commit(); service.close()
            service = QuizService(db, 'test')
            try:
                answer = service.clusters(teacher, activity['id'], '1')['clusters'][0]['answers'][0]
                self.assertEqual(0, answer['review_revision'])
                result = service.review_batch(teacher, activity['id'], '1', [{'id':answer['id'], 'revision':0}], 'correct')
            finally: service.close()
            service = QuizService(db, 'test')
            try:
                service.undo_review_batch(teacher, activity['id'], result['batch_id'])
                self.assertEqual(0, service.snapshot(student, activity['id'])['own_score']['total'])
            finally: service.close()
