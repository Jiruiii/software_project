import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quiz_service import QuizError, QuizService


class QuestionTimingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = Path(self.folder.name) / 'timing.sqlite3'
        self.clock_patch = patch('quiz_service.time.time', return_value=1000)
        self.clock = self.clock_patch.start()
        self.s = QuizService(self.db, 'test')
        self.t = self.s.login('test')['token']
        self.a = self.s.create(self.t, '計時', ['1', '2', '3'])
        self.aid = self.a['id']
        self.u = self.s.join(self.a['code'], 'A')['token']

    def tearDown(self):
        self.s.close(); self.clock_patch.stop(); self.folder.cleanup()

    def start_second(self, grouped=False, fairness=False):
        if grouped:
            self.s.db.execute("UPDATE question_meta SET unit_id='2' WHERE activity_id=? AND question_id='3'", (self.aid,)); self.s.db.commit()
        self.s.configure(self.t, self.aid, 'sequential', fairness)
        self.s.transition(self.t, self.aid, 'active')
        self.clock.return_value = 1001.25
        self.first = self.s.submit(self.u, self.aid, '1', 'first')
        self.s.round_action(self.t, self.aid, 'close')
        if fairness:
            self.s.db.execute('UPDATE group_progress SET misses=3'); self.s.db.commit()
        self.clock.return_value = 1060
        self.s.round_action(self.t, self.aid, 'next')

    def test_second_question_retry_csv_and_restart(self):
        self.start_second()
        self.clock.return_value = 1062.35
        answer = self.s.submit(self.u, self.aid, '2', 'second')
        self.assertEqual(2350, answer['elapsed_ms'])
        self.assertEqual('question', answer['elapsed_basis'])
        self.clock.return_value = 1068
        self.assertEqual(answer, self.s.submit(self.u, self.aid, '2', 'second'))
        self.s.round_action(self.t, self.aid, 'close')
        self.clock.return_value = 1200
        self.s.round_action(self.t, self.aid, 'next')
        self.s.transition(self.t, self.aid, 'results')
        self.s.close(); self.s = QuizService(self.db, 'test')
        state = self.s.snapshot(self.u, self.aid)
        self.assertEqual([1250, 2350], [a['elapsed_ms'] for a in state['answers']])
        self.assertEqual(1062.35, state['answers'][1]['received_at'])
        rows = list(csv.DictReader(io.StringIO(self.s.activity_csv(self.t, self.aid).decode('utf-8-sig'))))
        self.assertEqual('2.350', rows[1]['送出秒數'])
        self.assertEqual('該題開放', rows[1]['計時基準'])
        self.assertEqual('1', rows[1]['原始順位'])

    def test_all_questions_share_activity_start(self):
        self.s.transition(self.t, self.aid, 'active')
        self.clock.return_value = 1002.35
        for q in ['1', '2']:
            answer = self.s.submit(self.u, self.aid, q, 'answer')
            self.assertEqual(2350, answer['elapsed_ms'])
            self.assertEqual('question', answer['elapsed_basis'])

    def test_group_children_share_opening_and_receipt(self):
        self.start_second(grouped=True)
        self.clock.return_value = 1062.35
        answers = self.s.submit_unit(self.u, self.aid, '2', {'2':'a', '3':'b'}, 2)['answers']
        self.assertEqual([2350, 2350], [a['elapsed_ms'] for a in answers])
        self.assertEqual([1062.35, 1062.35], [a['received_at'] for a in answers])

    def test_fairness_uses_common_opening_including_priority(self):
        self.start_second(fairness=True)
        other = self.s.join(self.a['code'], 'B')['token']
        self.clock.return_value = 1060.5
        self.assertEqual(500, self.s.submit(self.u, self.aid, '2', 'priority')['elapsed_ms'])
        with self.assertRaises(QuizError): self.s.submit(other, self.aid, '2', 'other')
        self.clock.return_value = 1063.25
        self.assertEqual(3250, self.s.submit(other, self.aid, '2', 'other')['elapsed_ms'])

    def test_legacy_last_round_recovery_and_unknown_earlier_round(self):
        self.start_second()
        self.clock.return_value = 1062.35
        self.s.submit(self.u, self.aid, '2', 'second')
        self.s.transition(self.t, self.aid, 'results')
        self.s.db.execute("UPDATE answers SET elapsed_ms=62350 WHERE question_id='2'")
        self.s.db.execute('ALTER TABLE answers DROP COLUMN elapsed_basis')
        self.s.db.execute('ALTER TABLE question_meta DROP COLUMN opened_at')
        self.s.db.commit(); self.s.close()
        for _ in range(2):
            self.s = QuizService(self.db, 'test')
            state = self.s.snapshot(self.u, self.aid)
            self.assertEqual([1250, 2350], [a['elapsed_ms'] for a in state['answers']])
            self.assertEqual(['activity', 'question'], [a['elapsed_basis'] for a in state['answers']])
            rows = list(csv.DictReader(io.StringIO(self.s.activity_csv(self.t, self.aid).decode('utf-8-sig'))))
            self.assertEqual('活動開始（舊紀錄）', rows[0]['計時基準'])
            self.assertEqual('該題開放', rows[1]['計時基準'])
            self.s.close()
        self.s = QuizService(self.db, 'test')

    def test_legacy_all_mode_recovery(self):
        self.s.transition(self.t, self.aid, 'active')
        self.clock.return_value = 1002.35
        self.s.submit(self.u, self.aid, '2', 'answer')
        self.s.db.execute('ALTER TABLE answers DROP COLUMN elapsed_basis')
        self.s.db.execute('ALTER TABLE question_meta DROP COLUMN opened_at')
        self.s.db.commit(); self.s.close(); self.s = QuizService(self.db, 'test')
        answer = self.s.snapshot(self.u, self.aid)['answers'][0]
        self.assertEqual(2350, answer['elapsed_ms'])
        self.assertEqual('question', answer['elapsed_basis'])
