import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from app import make_server
from quiz_service import QuizError, QuizService
from guided_notes import from_xlsx, parse_grid
from test_guided_notes import payload
import test_sheet_auto_sync as sync_tests


class TeacherReferenceTests(unittest.TestCase):
    setUp = sync_tests.AutoSyncTests.setUp
    tearDown = sync_tests.AutoSyncTests.tearDown
    close_first = sync_tests.AutoSyncTests.close_first
    value = sync_tests.AutoSyncTests.value
    state = sync_tests.AutoSyncTests.state

    def test_override_cancel_and_all_wrong_leave_scores_unchanged(self):
        self.close_first()
        before = self.s.snapshot(self.u,self.aid)['own_score']
        self.s.reference(self.t,self.aid,'1','=teacher',True); self.auto.run_once()
        self.assertEqual('=teacher（老師答案）',self.value())
        self.assertEqual(before,self.s.snapshot(self.u,self.aid)['own_score'])
        self.assertEqual({'1':'=teacher'},self.s.snapshot(self.u,self.aid)['references'])
        self.assertNotIn('reference_overrides',self.s.snapshot(self.u,self.aid))
        self.s.review(self.t,self.aid,self.ids[0],'incorrect'); self.auto.run_once()
        self.assertEqual('=teacher（老師答案）',self.value())
        self.assertFalse(self.s.snapshot(self.t,self.aid)['source']['export_stale'])
        self.s.reference(self.t,self.aid,'1','=teacher',False); self.auto.run_once()
        self.assertEqual('second（B）',self.value())
        self.s.review(self.t,self.aid,self.ids[1],'incorrect'); self.auto.run_once()
        self.s.reference(self.t,self.aid,'1','everyone wrong',True); self.auto.run_once()
        self.assertEqual('everyone wrong（老師答案）',self.value())
        self.s.reference(self.t,self.aid,'1','everyone wrong',False); self.auto.run_once()
        self.assertEqual('',self.value())
        self.s.transition(self.t,self.aid,'results')
        self.assertEqual('everyone wrong',self.s.snapshot(self.u,self.aid)['report'][0]['reference'])

    def test_phase_validation_and_reference_only(self):
        with self.assertRaises(QuizError): self.s.reference(self.t,self.aid,'1','x',True)
        self.close_first()
        for token,q,answer,override in [(self.u,'1','x',True),(self.t,'2','x',True),(self.t,'missing','x',False),
                                      (self.t,'1',' ',True),(self.t,'1','x','true'),(self.t,'1','x'*2001,False)]:
            with self.assertRaises(QuizError): self.s.reference(token,self.aid,q,answer,override)
        self.s.reference(self.t,self.aid,'1','reference only')
        self.auto.run_once(); self.assertEqual('=first（A）',self.value())
        self.s.reference(self.t,self.aid,'1',''); self.auto.run_once()
        self.assertEqual('=first（A）',self.value())
        a=self.s.create(self.t,'manual',['1'])
        self.s.transition(self.t,a['id'],'active'); self.s.transition(self.t,a['id'],'results')
        self.s.reference(self.t,a['id'],'1','manual reference')
        with self.assertRaises(QuizError): self.s.reference(self.t,a['id'],'1','x',True)

    def test_all_mode_and_timer_closed_without_answers(self):
        self.s.configure(self.t,self.aid,'all',duration_seconds=3)
        with patch('quiz_service.time.time',return_value=1000) as clock:
            self.s.transition(self.t,self.aid,'active')
            with self.assertRaises(QuizError): self.s.reference(self.t,self.aid,'1','early',True)
            clock.return_value=1004
            self.s.reference(self.t,self.aid,'1','no submissions',True)
            self.auto.run_once()
        self.assertEqual('no submissions（老師答案）',self.value())

    def test_grouped_child_override_and_cancel(self):
        grid=from_xlsx((Path(__file__).parent/'fixtures/grouped.xlsx').read_bytes())[0]
        self.g.data=payload(grid)
        source=parse_grid(grid);source['spreadsheet_id']='test-reference-grouped-12345'
        a=self.s.create_from_source(self.t,'grouped',source);aid=a['id']
        u=self.s.join(a['code'],'group')['token']
        self.s.configure(self.t,aid,'sequential');self.auto.watch(self.t,aid)
        self.s.transition(self.t,aid,'active');self.s.submit_unit(u,aid,'1',{'1.1':'a','1.2':'b'})
        self.s.round_action(self.t,aid,'close')
        self.s.reference(self.t,aid,'1.1','teacher child',True);self.auto.run_once()
        targets=[t for t in source['targets'] if t['unit']=='1']
        self.assertEqual(['teacher child（老師答案）','b（group）'],[self.value(t['row'],t['col']) for t in targets])
        self.s.reference(self.t,aid,'1.1','teacher child',False);self.auto.run_once()
        self.assertEqual(['a（group）','b（group）'],[self.value(t['row'],t['col']) for t in targets])

    def test_override_during_write_converges_and_external_edit_protected(self):
        self.close_first()
        self.s.reference(self.t,self.aid,'1','old teacher',True)
        entered,release=threading.Event(),threading.Event(); original=self.g.request
        def slow(owner,sid,body=None):
            if body is not None:
                entered.set()
                if not release.wait(3): raise AssertionError('not released')
            return original(owner,sid,body)
        self.g.request=slow
        worker=threading.Thread(target=self.auto.run_once);worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.s.reference(self.t,self.aid,'1','latest teacher',True)
        finally: release.set();worker.join(4)
        self.auto.run_once();self.assertEqual('latest teacher（老師答案）',self.value())
        self.g.data['sheets'][0]['data'][0]['rowData'][4]['values'][6]['userEnteredValue']={'stringValue':'external'}
        self.s.reference(self.t,self.aid,'1','latest teacher',False);self.auto.run_once()
        self.assertEqual('error',self.state());self.assertEqual('external',self.value())

    def test_migration_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reference.sqlite3'
            s=QuizService(path,'test');t=s.login('test')['token']
            source=json.loads(self.s.db.execute('SELECT source_json FROM sheet_sources').fetchone()[0])
            aid=s.create_from_source(t,'legacy',source)['id']
            s.transition(t,aid,'active');s.transition(t,aid,'results')
            s.reference(t,aid,'1','legacy reference')
            s.db.execute('ALTER TABLE question_meta DROP COLUMN reference_override');s.db.commit();s.close()
            s=QuizService(path,'test')
            self.assertFalse(s.snapshot(t,aid)['reference_overrides']['1'])
            self.assertEqual('legacy reference',s.snapshot(t,aid)['references']['1'])
            s.reference(t,aid,'1','persisted',True);s.close()
            s=QuizService(path,'test')
            try:
                self.assertTrue(s.snapshot(t,aid)['reference_overrides']['1'])
                self.assertEqual('persisted（老師答案）',s.export_context(t,aid)[1]['1'])
            finally:s.close()

    def test_http_reference_option(self):
        self.close_first();server=make_server(self.s,0,self.flow)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def post(token,override):
            req=Request(f'http://127.0.0.1:{server.server_port}/api/activities/{self.aid}/reference',
                        data=json.dumps({'question':'1','answer':'HTTP teacher','override':override}).encode(),
                        headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
            try:r=urlopen(req,timeout=3)
            except HTTPError as e:r=e
            with r:return r.status
        try:
            self.assertEqual(403,post(self.u,True));self.assertEqual(400,post(self.t,1))
            self.assertEqual(200,post(self.t,True))
            self.assertEqual('HTTP teacher（老師答案）',self.s.export_context(self.t,self.aid)[1]['1'])
        finally:server.shutdown();worker.join();server.server_close()
