import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quiz_service import QuizService, QuizError
from google_sheets import SheetsWorkflow
from guided_notes import from_google
from test_google_sheets import FakeGoogle, COPY_URL


class FairnessReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'flow.sqlite3'
        self.s=QuizService(self.path,'test');self.t=self.s.login('test')['token']
        self.a=self.s.create(self.t,'fairness',['1','2','3','4','5']);self.aid=self.a['id']
        self.u=self.s.join(self.a['code'],'A')['token'];self.v=self.s.join(self.a['code'],'B')['token']
        self.s.configure(self.t,self.aid,'sequential',True)
        self.clock=patch('quiz_extras.time.time',return_value=1000);self.clock.start()
        self.s.transition(self.t,self.aid,'active')
    def tearDown(self): self.clock.stop();self.s.close();self.folder.cleanup()
    def test_total_includes_speed_and_wager_and_handles_ties(self):
        self.s.submit(self.u,self.aid,'1','A',0)
        self.s.submit(self.v,self.aid,'1','B',3)
        self.s.round_action(self.t,self.aid,'close')
        for answer in self.s.snapshot(self.t,self.aid)['answers']:
            self.s.review(self.t,self.aid,answer['id'],'correct')
        self.s.round_action(self.t,self.aid,'next')
        # A: 0+4; B: 3+2. Only A gets priority.
        self.assertTrue(self.s.snapshot(self.u,self.aid)['round']['own_priority'])
        self.assertFalse(self.s.snapshot(self.v,self.aid)['round']['own_priority'])
        self.s.round_action(self.t,self.aid,'close')
        late=[self.s.join(self.a['code'],name)['token'] for name in ('C','D')]
        self.s.round_action(self.t,self.aid,'next')
        for token in late: self.assertTrue(self.s.snapshot(token,self.aid)['round']['own_priority'])
        for token in (self.u,self.v): self.assertFalse(self.s.snapshot(token,self.aid)['round']['own_priority'])

    def test_batch_regrade_and_restart_do_not_change_open_round(self):
        self.s.submit(self.u,self.aid,'1','A',3)
        self.s.round_action(self.t,self.aid,'close')
        answer=self.s.snapshot(self.t,self.aid)['answers'][0]
        batch=self.s.review_batch(self.t,self.aid,'1',[{'id':answer['id'],'revision':0}],'correct')
        self.s.round_action(self.t,self.aid,'next')
        before=self.s.snapshot(self.v,self.aid)['round']
        self.assertTrue(before['own_priority'])
        self.s.undo_review_batch(self.t,self.aid,batch['batch_id'])
        self.s.review(self.t,self.aid,answer['id'],'incorrect')
        self.s.close();self.s=QuizService(self.path,'test')
        self.assertEqual(before,self.s.snapshot(self.v,self.aid)['round'])
        self.s.round_action(self.t,self.aid,'close');self.s.round_action(self.t,self.aid,'next')
        self.assertTrue(self.s.snapshot(self.u,self.aid)['round']['own_priority'])
        self.assertFalse(self.s.snapshot(self.v,self.aid)['round']['own_priority'])

    def test_empty_roster_has_no_priority_window(self):
        a=self.s.create(self.t,'empty',['1'])
        self.s.configure(self.t,a['id'],'sequential',True)
        self.s.transition(self.t,a['id'],'active')
        late=self.s.join(a['code'],'late')['token']
        self.assertEqual(0,self.s.snapshot(late,a['id'])['round']['priority_until'])
        self.s.submit(late,a['id'],'1','立即')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'recovery.sqlite3'
        self.s=QuizService(self.path,'test');self.t=self.s.login('test')['token'];self.g=FakeGoogle();self.f=SheetsWorkflow(self.s,self.g)
        self.a=self.f.import_activity(self.t,self.f.preview(self.t,COPY_URL)['preview_id'],'recovery');self.aid=self.a['id']
        self.u=self.s.join(self.a['code'],'A')['token'];self.v=self.s.join(self.a['code'],'B')['token']
        self.s.transition(self.t,self.aid,'active');self.s.submit(self.u,self.aid,'1','first');self.s.submit(self.v,self.aid,'1','second');self.s.transition(self.t,self.aid,'results')
    def tearDown(self):self.s.close();self.folder.cleanup()
    def value(self):return from_google(self.g.data)[0].value(4,6)
    def fail_after_write(self,readback=True,answer_col=6):
        original=self.g.request;state={'wrote':False}
        def flaky(owner,sid,body=None):
            if readback and body is None and state['wrote']:raise QuizError(502,'readback outage')
            result=original(owner,sid,body)
            if body:
                state['wrote']=True
                if not readback:raise QuizError(502,'lost response')
            return result
        self.g.request=flaky
        with self.assertRaises(QuizError):self.f.export(self.t,self.aid)
        self.g.request=original
        self.assertIsNone(self.s.snapshot(self.t,self.aid)['source']['exported_at'])
        self.assertEqual('first（A）',from_google(self.g.data)[0].value(4,answer_col))
    def regrade(self):self.s.review(self.t,self.aid,self.s.snapshot(self.t,self.aid)['answers'][0]['id'],'incorrect')
    def test_readback_failure_then_regrade_recovers(self):
        self.fail_after_write();self.regrade();self.f.export(self.t,self.aid)
        self.assertEqual('second（B）',self.value())
        self.assertNotIn('pending_export',self.s.export_context(self.t,self.aid)[0])
    def test_lost_response_restart_and_teacher_override(self):
        self.fail_after_write(False);self.s.reference(self.t,self.aid,'1','teacher',True)
        self.s.close();self.s=QuizService(self.path,'test');self.f=SheetsWorkflow(self.s,self.g)
        self.f.export(self.t,self.aid);self.assertEqual('teacher（老師答案）',self.value())
    def test_not_written_then_retry_and_idempotent(self):
        self.g.fail=True
        with self.assertRaises(QuizError):self.f.export(self.t,self.aid)
        self.assertEqual('',self.value());self.g.fail=False;self.regrade()
        self.f.export(self.t,self.aid);self.f.export(self.t,self.aid)
        self.assertEqual('second（B）',self.value());self.assertEqual(1,len(self.g.writes))
    def test_external_modification_is_never_overwritten(self):
        self.fail_after_write()
        self.g.data['sheets'][0]['data'][0]['rowData'][4]['values'][6]['userEnteredValue']={'stringValue':'external'}
        self.regrade()
        with self.assertRaisesRegex(QuizError,'已被修改'):self.f.export(self.t,self.aid)
        self.assertEqual('external',self.value())
        self.assertIn('pending_export',self.s.export_context(self.t,self.aid)[0])

    def test_grouped_recovery_replaces_only_the_incorrect_child(self):
        from guided_notes import from_xlsx
        from test_guided_notes import payload
        self.g.data=payload(from_xlsx((Path(__file__).parent/'fixtures/grouped.xlsx').read_bytes())[0])
        a=self.f.import_activity(self.t,self.f.preview(self.t,COPY_URL)['preview_id'],'grouped');self.aid=a['id']
        u=self.s.join(a['code'],'A')['token'];v=self.s.join(a['code'],'B')['token']
        self.s.transition(self.t,self.aid,'active')
        self.s.submit_unit(u,self.aid,'1',{'1.1':'first','1.2':'a child'})
        self.s.submit_unit(v,self.aid,'1',{'1.1':'second','1.2':'b child'})
        self.s.transition(self.t,self.aid,'results');self.fail_after_write(answer_col=7);self.regrade();self.f.export(self.t,self.aid)
        grid=from_google(self.g.data)[0]
        self.assertEqual(['second（B）','a child（A）'],[grid.value(4,7),grid.value(5,7)])
        self.assertEqual({'pending_answers':3,'complete':False},self.s.snapshot(u,self.aid)['grading'])
        for answer in self.s.snapshot(self.t,self.aid)['answers']:
            if answer['verdict']=='pending': self.s.review(self.t,self.aid,answer['id'],'correct')
        self.assertTrue(self.s.snapshot(v,self.aid)['grading']['complete'])


class GradingStateTests(unittest.TestCase):
    def test_pending_complete_undo_and_empty(self):
        s=QuizService(':memory:','test');t=s.login('test')['token'];a=s.create(t,'grading',['1']);aid=a['id'];u=s.join(a['code'],'A')['token']
        try:
            s.transition(t,aid,'active');s.submit(u,aid,'1','a',3)
            self.assertNotIn('grading',s.snapshot(u,aid))
            s.transition(t,aid,'results')
            self.assertEqual({'pending_answers':1,'complete':False},s.snapshot(u,aid)['grading'])
            self.assertIn('暫時成績',s.report_csv(u,aid).decode('utf-8-sig'))
            answer=s.snapshot(t,aid)['answers'][0]
            batch=s.review_batch(t,aid,'1',[{'id':answer['id'],'revision':0}],'correct')
            self.assertTrue(s.snapshot(u,aid)['grading']['complete']);self.assertEqual(7,s.snapshot(u,aid)['own_score']['total'])
            self.assertIn('批改完成',s.report_csv(u,aid).decode('utf-8-sig'))
            s.undo_review_batch(t,aid,batch['batch_id']);self.assertFalse(s.snapshot(u,aid)['grading']['complete'])
            empty=s.create(t,'empty',['1']);s.transition(t,empty['id'],'active');s.transition(t,empty['id'],'results')
            self.assertTrue(s.snapshot(t,empty['id'])['grading']['complete'])
            choice=s.create(t,'choice',['1']);cid=choice['id']
            s.question_settings(t,cid,'1',True,[{'question':'1','type':'choice','options':['a','b'],'correct_index':0}])
            v=s.join(choice['code'],'B')['token'];s.transition(t,cid,'active');s.submit(v,cid,'1','a',2);s.transition(t,cid,'results')
            self.assertTrue(s.snapshot(v,cid)['grading']['complete'])
        finally:s.close()
