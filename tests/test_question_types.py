import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from app import make_server
from quiz_service import QuizService, QuizError
from guided_notes import from_xlsx, parse_grid, from_google
from google_sheets import SheetsWorkflow
from test_google_sheets import FakeGoogle, COPY_URL


def choice(q='1', options=None, correct=1):
    return {'question':q,'type':'choice','options':options or ['甲','乙','丙'],'correct_index':correct}


class QuestionTypeTests(unittest.TestCase):
    def setUp(self):
        self.s=QuizService(':memory:','password')
        self.t=self.s.login('password')['token']; self.a=self.s.create(self.t,'types',['1','2'])
        self.aid=self.a['id']; self.u=self.s.join(self.a['code'],'A')['token']; self.v=self.s.join(self.a['code'],'B')['token']

    def tearDown(self): self.s.close()

    def test_no_bet_default_switch_and_all_groups_autograded(self):
        self.s.question_settings(self.t,self.aid,'1',True,[choice()])
        self.s.question_settings(self.t,self.aid,'2',False,[choice('2')])
        self.s.transition(self.t,self.aid,'active')
        wrong=self.s.submit(self.u,self.aid,'1','甲',3)
        right=self.s.submit(self.v,self.aid,'1','乙',2)
        self.assertEqual('withheld',wrong['verdict']); self.assertEqual('withheld',right['verdict'])
        self.assertEqual(['incorrect','correct'],[a['verdict'] for a in self.s.snapshot(self.t,self.aid)['answers']])
        with self.assertRaises(QuizError): self.s.submit(self.u,self.aid,'2','乙',1)
        no_bet=self.s.submit(self.u,self.aid,'2','乙')
        self.assertEqual((0,'withheld'),(no_bet['stake'],no_bet['verdict']))
        self.assertEqual(no_bet,self.s.submit(self.u,self.aid,'2','乙',0))
        with self.assertRaises(QuizError): self.s.submit(self.v,self.aid,'2','偽造選項',0)
        self.s.transition(self.t,self.aid,'results')
        state=self.s.snapshot(self.t,self.aid)
        self.assertEqual('B',state['results'][0]['winner']['group_name'])
        self.assertEqual([2,-3],[r['score'] for r in state['scoreboard']])

    def test_configuration_validation_stage_and_secret_filter(self):
        self.s.question_settings(self.t,self.aid,'1',True,[choice()])
        before=self.s.snapshot(self.t,self.aid)['question_settings']
        for item in [choice(options=['x']),choice(options=['x','x']),choice(options=[' ','y']),
                     choice(correct=True),choice(correct=-1),choice(correct=3),
                     choice(options=['x'*201,'y']), {'question':'1','type':'unknown'}, choice('2')]:
            with self.assertRaises(QuizError): self.s.question_settings(self.t,self.aid,'1',True,[item])
        with self.assertRaises(QuizError): self.s.question_settings(self.u,self.aid,'1',True,[choice()])
        with self.assertRaises(QuizError): self.s.question_settings(self.t,self.aid,'1',1,[choice()])
        self.assertEqual(before,self.s.snapshot(self.t,self.aid)['question_settings'])
        student=self.s.snapshot(self.u,self.aid)
        self.assertNotIn('correct_index',json.dumps(student)); self.assertNotIn('scoreboard',student)
        self.s.transition(self.t,self.aid,'active')
        with self.assertRaises(QuizError): self.s.question_settings(self.t,self.aid,'1',False,[choice()])

    def test_mixed_bundle_atomicity_manual_review_and_retry(self):
        source=parse_grid(from_xlsx((Path(__file__).parent/'fixtures/grouped.xlsx').read_bytes())[0]); source['spreadsheet_id']='fixture-grouped-id-12345'
        a=self.s.create_from_source(self.t,'mixed',source); aid=a['id']; u=self.s.join(a['code'],'A')['token']
        self.s.question_settings(self.t,aid,'1',True,[choice('1.1'),{'question':'1.2','type':'short'}])
        self.s.question_settings(self.t,aid,'2',True,[choice('2.1'),choice('2.2')])
        before=self.s.snapshot(self.t,aid)['question_settings']
        with self.assertRaises(QuizError): self.s.question_settings(self.t,aid,'1',False,[choice('1.1'),choice('1.2',correct=8)])
        self.assertEqual(before,self.s.snapshot(self.t,aid)['question_settings'])
        self.s.transition(self.t,aid,'active')
        with self.assertRaises(QuizError): self.s.submit_unit(u,aid,'2',{'2.1':'乙','2.2':'invalid'},3)
        with self.assertRaises(QuizError): self.s.submit_unit(u,aid,'1',{'1.1':'invalid','1.2':'valid'},3)
        self.assertEqual([],self.s.snapshot(self.t,aid)['answers'])
        result=self.s.submit_unit(u,aid,'1',{'1.1':'乙','1.2':'簡答'},3)
        self.assertEqual(['withheld','withheld'],[a['verdict'] for a in result['answers']])
        self.assertEqual(['correct','pending'],[a['verdict'] for a in self.s.snapshot(self.t,aid)['answers']])
        self.assertEqual(result,self.s.submit_unit(u,aid,'1',{'1.1':'乙','1.2':'簡答'},3))
        self.s.transition(self.t,aid,'results')
        rows=self.s.snapshot(self.t,aid)['answers']; self.s.review(self.t,aid,rows[1]['id'],'correct')
        self.assertEqual(3,self.s.snapshot(u,aid)['scoreboard'][0]['score'])
        self.s.review(self.t,aid,rows[0]['id'],'incorrect')
        self.assertEqual(-3,self.s.snapshot(u,aid)['scoreboard'][0]['score'])

    def test_legacy_migration_preserves_stakes_and_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.sqlite3'; s=QuizService(path,'pw'); t=s.login('pw')['token']; a=s.create(t,'legacy',['1']); u=s.join(a['code'],'A')['token']
            s.transition(t,a['id'],'active'); original=s.submit(u,a['id'],'1','保留',3); s.close()
            db=sqlite3.connect(path)
            for name in ('question_type','options_json','correct_index','betting_enabled'): db.execute(f'ALTER TABLE question_meta DROP COLUMN {name}')
            db.commit(); db.close(); s=QuizService(path,'pw')
            try:
                self.assertEqual(original,s.snapshot(u,a['id'])['answers'][0])
                self.assertEqual('short',s.snapshot(t,a['id'])['question_settings']['1']['type'])
            finally: s.close()

    def test_choice_export_uses_correct_candidate_literal_text(self):
        google=FakeGoogle(); flow=SheetsWorkflow(self.s,google)
        preview=flow.preview(self.t,COPY_URL); a=flow.import_activity(self.t,preview['preview_id'],'choice export'); aid=a['id']
        self.s.question_settings(self.t,aid,'1',True,[choice(options=['錯誤','=1+1'])])
        auser=self.s.join(a['code'],'A')['token']; buser=self.s.join(a['code'],'B')['token']
        self.s.transition(self.t,aid,'active'); self.s.submit(auser,aid,'1','錯誤',3); self.s.submit(buser,aid,'1','=1+1',2)
        self.s.transition(self.t,aid,'results'); flow.export(self.t,aid)
        self.assertEqual('=1+1（B）',from_google(google.data)[0].value(4,6))
        self.assertEqual({'stringValue':'=1+1（B）'},google.writes[0][1]['requests'][0]['updateCells']['rows'][0]['values'][0]['userEnteredValue'])

    def test_thirty_groups_choice_scores_and_unique_correct_winner(self):
        self.s.question_settings(self.t,self.aid,'1',True,[choice()])
        people=[self.s.join(self.a['code'],f'組{i:02}')['token'] for i in range(30)]
        self.s.transition(self.t,self.aid,'active')
        def send(i): return self.s.submit(people[i],self.aid,'1','乙' if i%2==0 else '甲',i%3+1)
        with ThreadPoolExecutor(max_workers=30) as pool: replies=list(pool.map(send,range(30)))
        self.assertTrue(all(a['verdict']=='withheld' for a in replies))
        self.assertEqual(15,sum(a['verdict']=='correct' for a in self.s.snapshot(self.t,self.aid)['answers']))
        for i,token in enumerate(people):
            own=self.s.snapshot(token,self.aid)
            self.assertEqual(0,own['own_score']['total'])
            self.assertEqual(1,len(own['answers'])); self.assertNotIn('scoreboard',own)
        self.s.transition(self.t,self.aid,'results'); state=self.s.snapshot(self.t,self.aid)
        for i,token in enumerate(people):
            self.assertEqual((i%3+1)*(1 if i%2==0 else -1),self.s.snapshot(token,self.aid)['own_score']['total'])
        first=next(a for a in state['answers'] if a['verdict']=='correct')
        self.assertEqual(first['group_name'],state['results'][0]['winner']['group_name'])

    def test_live_own_score_privacy_regrade_and_activity_isolation(self):
        self.s.question_settings(self.t,self.aid,'1',True,[choice()])
        self.s.configure(self.t,self.aid,'sequential')
        self.s.transition(self.t,self.aid,'active')
        self.s.submit(self.u,self.aid,'1','乙',3); self.s.submit(self.v,self.aid,'1','甲',2)
        own=self.s.snapshot(self.u,self.aid); other=self.s.snapshot(self.v,self.aid)
        self.assertEqual({'total':0,'pending_units':0,'awaiting_close_units':1},own['own_score'])
        self.assertEqual(own['own_score'],other['own_score'])
        for key in ('groups','results','scoreboard'): self.assertNotIn(key,own)
        self.assertNotIn('correct_index',json.dumps(own))
        self.s.round_action(self.t,self.aid,'close')
        self.assertEqual(3,self.s.snapshot(self.u,self.aid)['own_score']['total'])
        self.assertEqual(-2,self.s.snapshot(self.v,self.aid)['own_score']['total'])
        answer=self.s.snapshot(self.t,self.aid)['answers'][0]
        self.s.review(self.t,self.aid,answer['id'],'incorrect')
        self.assertEqual(-3,self.s.snapshot(self.u,self.aid)['own_score']['total'])
        self.s.round_action(self.t,self.aid,'next')
        self.s.submit(self.u,self.aid,'2','待批改',2)
        self.assertEqual({'total':-3,'pending_units':0,'awaiting_close_units':1},self.s.snapshot(self.u,self.aid)['own_score'])
        self.s.transition(self.t,self.aid,'results')
        self.assertEqual({'total':-3,'pending_units':1,'awaiting_close_units':0},self.s.snapshot(self.u,self.aid)['own_score'])
        rows=self.s.snapshot(self.t,self.aid)['answers']; self.s.review(self.t,self.aid,rows[-1]['id'],'correct')
        self.assertEqual({'total':-1,'pending_units':0,'awaiting_close_units':0},self.s.snapshot(self.u,self.aid)['own_score'])
        a=self.s.create(self.t,'new',['1']); u=self.s.join(a['code'],'A')['token']
        self.assertEqual(0,self.s.snapshot(u,a['id'])['own_score']['total'])
        with self.assertRaises(QuizError): self.s.snapshot(self.u,a['id'])

    def test_http_does_not_accept_client_verdict_or_score(self):
        server=make_server(self.s,0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        def post(action,data,token):
            request=Request(f'http://127.0.0.1:{server.server_port}/api/activities/{self.aid}/{action}',
                            data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
            with urlopen(request) as response: return json.load(response)
        try:
            with self.assertRaises(HTTPError) as error: post('question-settings',{'unit':'1','betting_enabled':True,'questions':[choice()]},self.u)
            self.assertEqual(403,error.exception.code); error.exception.close()
            post('question-settings',{'unit':'1','betting_enabled':True,'questions':[choice()]},self.t)
            self.s.transition(self.t,self.aid,'active')
            result=post('answers',{'question':'1','answer':'甲','verdict':'correct','score':999,'correct_index':0},self.u)
            self.assertEqual('withheld',result['verdict']); self.assertEqual(0,result['stake'])
            self.assertEqual('incorrect',self.s.snapshot(self.t,self.aid)['answers'][0]['verdict'])
        finally: server.shutdown(); thread.join(); server.server_close()


if __name__ == '__main__': unittest.main()
