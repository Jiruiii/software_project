import threading
import unittest
from unittest.mock import patch

from google_sheets import SheetsWorkflow
from guided_notes import from_google, from_xlsx, parse_grid, SINGLE_TEMPLATE
from pathlib import Path
from quiz_service import QuizError, QuizService
from sheet_auto_sync import SheetsAutoSync
from test_google_sheets import FakeGoogle, COPY_URL
from test_guided_notes import payload


class AutoSyncTests(unittest.TestCase):
    def setUp(self):
        self.s = QuizService(':memory:', 'test')
        self.t = self.s.login('test')['token']
        self.g = FakeGoogle()
        self.flow = SheetsWorkflow(self.s, self.g)
        preview = self.flow.preview(self.t, COPY_URL)
        self.a = self.flow.import_activity(self.t, preview['preview_id'], 'auto sync')
        self.aid = self.a['id']
        self.u = self.s.join(self.a['code'], 'A')['token']
        self.v = self.s.join(self.a['code'], 'B')['token']
        self.auto = SheetsAutoSync(self.flow)
        self.auto.watch(self.t, self.aid)

    def tearDown(self):
        self.auto.close(); self.s.close()

    def close_first(self):
        self.s.configure(self.t, self.aid, 'sequential')
        self.s.transition(self.t, self.aid, 'active')
        self.s.submit(self.u, self.aid, '1', '=first', 3)
        self.s.submit(self.v, self.aid, '1', 'second', 2)
        self.auto.run_once()
        self.assertEqual([], self.g.writes)
        self.s.round_action(self.t, self.aid, 'close')
        self.auto.run_once()
        self.ids = [a['id'] for a in self.s.snapshot(self.t, self.aid)['answers']]

    def value(self, row=4, col=6): return from_google(self.g.data)[0].value(row, col)
    def state(self): return self.s.snapshot(self.t, self.aid)['source']['sync']['state']

    def test_close_regrade_restore_and_no_redundant_requests(self):
        self.close_first()
        self.assertEqual('=first（A）', self.value())
        self.assertEqual('active', self.s.snapshot(self.t, self.aid)['phase'])
        self.assertEqual('synced', self.state())
        self.assertEqual(1, len(self.g.writes[0][1]['requests']))
        original = self.g.request
        calls = []
        def counted(*args): calls.append(args); return original(*args)
        self.g.request = counted
        self.auto.run_once(); self.auto.run_once()
        self.assertEqual([], calls)
        self.s.review(self.t, self.aid, self.ids[0], 'correct'); self.auto.run_once()
        self.assertEqual([], calls)
        self.assertFalse(self.s.snapshot(self.t,self.aid)['source']['export_stale'])
        self.s.review(self.t, self.aid, self.ids[0], 'incorrect'); self.auto.run_once()
        self.assertEqual('second（B）', self.value())
        self.s.review(self.t, self.aid, self.ids[1], 'incorrect'); self.auto.run_once()
        self.assertEqual('', self.value())
        self.s.review(self.t, self.aid, self.ids[0], 'correct'); self.auto.run_once()
        self.assertEqual('=first（A）', self.value())
        self.s.round_action(self.t, self.aid, 'next')
        self.s.submit(self.u, self.aid, '2', 'unpublished')
        calls.clear(); self.auto.run_once()
        self.assertEqual([], calls)
        self.assertNotIn('unpublished', str(self.g.writes))

    def test_batch_and_undo_sync_original_candidate(self):
        self.close_first()
        selections = [{'id':a['id'], 'revision':a['review_revision']} for a in self.s.snapshot(self.t, self.aid)['answers']]
        batch = self.s.review_batch(self.t, self.aid, '1', selections, 'incorrect')
        self.auto.run_once(); self.assertEqual('', self.value())
        self.s.undo_review_batch(self.t, self.aid, batch['batch_id'])
        self.auto.run_once(); self.assertEqual('=first（A）', self.value())
        self.assertEqual('pending', self.s.snapshot(self.t, self.aid)['answers'][0]['verdict'])

    def test_quick_regrade_reversal_confirms_same_candidate(self):
        self.close_first()
        self.s.review(self.t, self.aid, self.ids[0], 'incorrect')
        self.s.review(self.t, self.aid, self.ids[0], 'correct')
        self.assertEqual('queued', self.state())
        self.auto.run_once()
        self.assertEqual('synced', self.state())
        self.assertFalse(self.s.snapshot(self.t, self.aid)['source']['export_stale'])
        self.assertEqual(1, len(self.g.writes))

    def test_failure_retry_and_external_edit_protection(self):
        self.close_first()
        self.g.fail = True
        self.s.review(self.t, self.aid, self.ids[0], 'incorrect'); self.auto.run_once()
        self.assertEqual('error', self.state()); self.assertEqual('=first（A）', self.value())
        self.g.fail = False
        self.auto.run_once(); self.assertEqual('=first（A）', self.value())
        self.auto.watch(self.t, self.aid, retry=True); self.auto.run_once()
        self.assertEqual('second（B）', self.value())
        self.g.data['sheets'][0]['data'][0]['rowData'][4]['values'][6]['userEnteredValue'] = {'stringValue':'manual edit'}
        self.s.review(self.t, self.aid, self.ids[0], 'correct'); self.auto.run_once()
        self.assertEqual('error', self.state()); self.assertEqual('manual edit', self.value())

    def test_grant_loss_reconnect_and_ownership(self):
        self.close_first()
        owner = self.s.teacher_key(self.t)
        allowed = set()
        self.g.status = lambda key: {'configured':True, 'connected':key in allowed}
        self.s.review(self.t, self.aid, self.ids[0], 'incorrect'); self.auto.run_once()
        self.assertEqual('needs_auth', self.state()); self.assertEqual('=first（A）', self.value())
        allowed.add(owner); self.auto.watch(self.t, self.aid); self.auto.run_once()
        self.assertEqual('second（B）', self.value())
        other = self.s.login('test')['token']; self.auto.watch(other, self.aid)
        self.assertEqual(owner, self.auto.bindings[self.aid]['owner'])
        with self.assertRaises(QuizError): self.auto.watch(self.u, self.aid, retry=True)
        self.assertNotIn('source', self.s.snapshot(self.u, self.aid))
        self.s.logout(self.t); self.auto.run_once()
        self.assertEqual('needs_auth', self.s.snapshot(other, self.aid)['source']['sync']['state'])

    def test_slow_google_does_not_block_and_regrade_converges(self):
        self.close_first()
        self.s.review(self.t, self.aid, self.ids[0], 'incorrect')
        entered, release = threading.Event(), threading.Event()
        original = self.g.request
        def slow(owner, sid, body=None):
            if body is not None:
                entered.set()
                if not release.wait(3): raise AssertionError('Write was not released')
            return original(owner, sid, body)
        self.g.request = slow
        worker = threading.Thread(target=self.auto.run_once); worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.s.round_action(self.t, self.aid, 'next')
            self.s.submit(self.u, self.aid, '2', 'keeps working')
            self.s.review(self.t, self.aid, self.ids[0], 'correct')
        finally:
            release.set(); worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertEqual('queued', self.state())
        self.auto.run_once()
        self.assertEqual('=first（A）', self.value()); self.assertEqual('synced', self.state())

    def test_timer_and_all_mode_without_teacher_polling(self):
        self.s.configure(self.t, self.aid, 'sequential', duration_seconds=3)
        with patch('quiz_service.time.time', return_value=1000) as clock:
            self.s.transition(self.t, self.aid, 'active')
            self.s.submit(self.u, self.aid, '1', 'timer')
            clock.return_value = 1003; self.s.tick(); self.auto.run_once()
        self.assertEqual('timer（A）', self.value())
        second = self.flow.import_activity(self.t, self.flow.preview(self.t, COPY_URL)['preview_id'], 'all mode')
        user = self.s.join(second['code'], 'C')['token']
        self.auto.watch(self.t, second['id'])
        self.s.transition(self.t, second['id'], 'active')
        self.s.submit(user, second['id'], '1', 'all mode')
        self.auto.run_once(); self.assertEqual('timer（A）', self.value())
        self.s.transition(self.t, second['id'], 'results'); self.auto.run_once()
        self.assertEqual('all mode（C）', self.value())

    def test_grouped_round_syncs_only_the_reviewed_child(self):
        grid = from_xlsx((Path(__file__).parent/'fixtures/grouped.xlsx').read_bytes())[0]
        self.g.data = payload(grid)
        source = parse_grid(grid); source['spreadsheet_id'] = 'test-grouped-auto-id-12345'
        a = self.s.create_from_source(self.t, 'grouped', source); aid = a['id']
        first = self.s.join(a['code'], 'first')['token']; second = self.s.join(a['code'], 'second')['token']
        self.s.configure(self.t, aid, 'sequential'); self.auto.watch(self.t, aid)
        self.s.transition(self.t, aid, 'active')
        self.s.submit_unit(first, aid, '1', {'1.1':'a1','1.2':'a2'}, 1)
        self.s.submit_unit(second, aid, '1', {'1.1':'b1','1.2':'b2'}, 1)
        self.s.round_action(self.t, aid, 'close'); self.auto.run_once()
        answers = {(a['group_name'], a['question_id']): a for a in self.s.snapshot(self.t, aid)['answers']}
        targets = {t['question']: t for t in source['targets'] if t['unit']=='1'}

        def check_cells(first_child, second_child):
            for q, expected in [('1.1', first_child), ('1.2', second_child)]:
                target = targets[q]
                self.assertEqual(expected, self.value(target['row'], target['col']), q)

        check_cells('a1（first）', 'a2（first）')
        self.s.review(self.t, aid, answers['first','1.1']['id'], 'incorrect')
        self.auto.run_once()
        check_cells('b1（second）', 'a2（first）')
        writes = self.g.writes[-1][1]['requests']
        self.assertEqual([(targets['1.1']['row'], targets['1.1']['col'])],
                         [(w['updateCells']['start']['rowIndex'], w['updateCells']['start']['columnIndex']) for w in writes])

        # Each group now has one incorrect child, but each cell still has a candidate.
        self.s.review(self.t, aid, answers['second','1.2']['id'], 'incorrect')
        self.auto.run_once()
        check_cells('b1（second）', 'a2（first）')
        last = answers['second','1.1']
        batch = self.s.review_batch(self.t, aid, '1.1', [{'id':last['id'], 'revision':last['review_revision']}], 'incorrect')
        self.auto.run_once()
        check_cells(targets['1.1']['original'], 'a2（first）')
        self.s.undo_review_batch(self.t, aid, batch['batch_id'])
        self.auto.run_once()
        check_cells('b1（second）', 'a2（first）')
        self.s.review(self.t, aid, answers['first','1.1']['id'], 'correct')
        self.auto.run_once()
        check_cells('a1（first）', 'a2（first）')

    def test_official_and_structure_changes_remain_protected(self):
        self.close_first()
        self.g.data['sheets'][0]['data'][0]['rowData'][4]['values'][2]['userEnteredValue'] = {'stringValue':'changed question'}
        self.s.review(self.t, self.aid, self.ids[0], 'incorrect'); self.auto.run_once()
        self.assertEqual('error', self.state()); self.assertEqual('=first（A）', self.value())
        self.g.data = FakeGoogle().data
        preview = self.flow.preview(self.t, 'https://docs.google.com/spreadsheets/d/'+SINGLE_TEMPLATE+'/edit')
        a = self.flow.import_activity(self.t, preview['preview_id'], 'protected')
        self.auto.watch(self.t, a['id']); self.s.transition(self.t, a['id'], 'active'); self.s.transition(self.t, a['id'], 'results')
        self.auto.run_once()
        self.assertIn('官方範本', self.s.snapshot(self.t, a['id'])['source']['sync']['message'])
