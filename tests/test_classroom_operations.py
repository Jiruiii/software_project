import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_accounts import Courses
from quiz_service import QuizError, QuizService


class ClassroomOperationsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'class.sqlite3'
        self.connect()
        self.addCleanup(lambda: self.s.close())
        self.account('teacher', 'home')
        self.account('admin', 'grant', uid='teacher')
        self.course = self.account('teacher', 'create-course', title='自然')['course']
        self.teacher = self.room('teacher')
        self.account('assistant', 'home')
        self.account('teacher', 'assistant', course=self.course, uid='assistant')
        self.aid = self.s.create(self.teacher, '混合', ['1.1', '1.2', '2'],
                                 groups=[{'id':'1', 'questions':['1.1', '1.2']}])['id']
        self.assistant = self.room('assistant', aid=self.aid)
        self.students = []
        for name in ['甲', '乙', '丙']:
            self.account(name, 'create-team', course=self.course, name=name, password='class123')
            room = self.account(name, 'student-room', course=self.course, aid=self.aid)
            self.students.append(room['token'])

    def connect(self):
        self.s = QuizService(self.path, 'local')
        self.c = Courses(self.s, {'projectId':'fixture'}, 'admin', lambda uid, _: (uid, uid+'@example.org'))

    def account(self, actor, action, **data):
        return self.c.dispatch(actor, action, data)

    def room(self, uid, **data):
        return self.account(uid, 'staff-room', course=self.course, **data)['token']

    def state(self, token):
        return self.s.snapshot(token, self.aid)

    def selections(self, question):
        return [{'id':a['id'], 'revision':a['review_revision']} for a in self.state(self.teacher)['answers']
                if a['question_id'] == question]

    def test_classroom_flow_restart_regrading_and_atomic_undo(self):
        choice = {'question':'1.2', 'type':'choice', 'options':['甲','乙'], 'correct_index':0, 'reference':'提示二'}
        self.s.question_settings(self.teacher,self.aid,'1',True,[{'question':'1.1','type':'short','reference':'提示一'},choice])
        self.s.reference(self.teacher,self.aid,'2','最後公布')
        self.s.reference(self.teacher,self.aid,'2','')
        self.assertEqual('',self.state(self.teacher)['references']['2'])
        self.s.reference(self.teacher,self.aid,'2','最後公布')
        self.assertEqual({}, self.state(self.students[0])['references'])
        self.s.configure(self.teacher,self.aid,'all',duration_seconds=3600)
        self.s.transition(self.teacher,self.aid,'active')
        student=self.students[0]
        payload={'1.1':'文字','1.2':'乙'}
        with self.assertRaises(QuizError):
            self.s.submit_unit(student,self.aid,'1',{'1.1':'文字'},2)
        with self.assertRaises(QuizError):
            self.s.submit(student,self.aid,'1.1','文字',2)
        for token in self.students:
            self.s.submit_unit(token,self.aid,'1',payload,2)
        self.s.submit_unit(student,self.aid,'1',payload,2)
        self.assertEqual(6,len(self.state(self.teacher)['answers']))
        self.assertEqual({},self.state(student)['references'])
        deadline=self.state(student)['round']['deadline']
        before=self.state(self.teacher)['answers']
        with self.assertRaises(QuizError):
            self.s.close_question(self.assistant,self.aid,'1.1')
        self.s.close_question(self.teacher,self.aid,'1.2')
        self.s.close_question(self.teacher,self.aid,'1.1')
        self.s.close()
        self.connect()
        state=self.state(student)
        self.assertEqual([{'id':'1','questions':['1.1','1.2']},{'id':'2','questions':['2']}],state['units'])
        self.assertEqual(['2'],state['available_questions'])
        self.assertEqual(deadline,state['round']['deadline'])
        self.assertEqual({'1.1':'提示一','1.2':'提示二'},state['references'])
        self.assertEqual(-2,state['own_score']['total'])
        receipts=lambda rows: [(a['id'],a['received_at'],a['text'],a['stake']) for a in rows]
        self.assertEqual(receipts(before),receipts(self.state(self.teacher)['answers']))
        with self.assertRaises(QuizError):
            self.s.submit_unit(student,self.aid,'1',payload,2)
        self.s.submit(student,self.aid,'2','獨立',0)
        first, choice_answer = before[:2]
        self.s.review(self.assistant,self.aid,first['id'],'incorrect',0)
        self.s.review(self.assistant,self.aid,choice_answer['id'],'pending',0)
        self.assertEqual(-2,self.state(student)['own_score']['total'])
        self.s.review(self.assistant,self.aid,first['id'],'pending',1)
        self.assertEqual(0,self.state(student)['own_score']['total'])
        with self.assertRaisesRegex(QuizError,'已是待判定'):
            self.s.review(self.assistant,self.aid,first['id'],'pending',2)
        with self.assertRaises(QuizError):
            self.s.review(self.teacher,self.aid,first['id'],'correct',1)
        answers=self.state(self.teacher)['answers']
        self.assertEqual('pending',answers[1]['verdict'])
        self.assertEqual(('incorrect','pending','assistant@example.org'),
                         tuple(answers[1]['reviews'][-1][k] for k in ('previous_verdict','verdict','email')))
        grade=lambda: self.s.review_batch(self.teacher,self.aid,'1.1',self.selections('1.1'),'correct')['batch_id']
        batch=grade()
        self.s.logout(self.teacher)
        self.teacher=self.room('teacher')
        own=self.s.review_history(self.teacher,self.aid)['batches']
        self.assertEqual([(batch,3,'1.1','correct',True)],[(r['batch_id'],r['count'],r['question'],r['verdict'],r['can_undo']) for r in own])
        self.assertTrue(own[0]['created_at'])
        self.assertEqual([],self.s.review_history(self.assistant,self.aid)['batches'])
        self.assertEqual(3,self.s.undo_review_batch(self.teacher,self.aid,batch)['count'])
        with self.assertRaises(QuizError):
            self.s.undo_review_batch(self.teacher,self.aid,batch)
        batch=grade()
        changed=self.selections('1.1')[1]
        self.s.review(self.assistant,self.aid,changed['id'],'incorrect',changed['revision'])
        snapshot=self.state(self.teacher)['answers']
        with self.assertRaisesRegex(QuizError,'後續批改'):
            self.s.undo_review_batch(self.teacher,self.aid,batch)
        self.assertEqual(snapshot,self.state(self.teacher)['answers'])
        self.assertEqual('已有後續批改',self.s.review_history(self.teacher,self.aid)['batches'][0]['reason'])
        self.s.review(self.teacher,self.aid,choice_answer['id'],'correct',1)
        self.assertEqual({'wager':2,'speed':4,'total':6},self.state(student)['own_points'])
        self.assertEqual({'rank':1,'group_name':'甲','score':6},self.state(student)['top_five'][0])
        self.s.close_question(self.teacher,self.aid,'2')
        self.assertEqual('active',self.state(student)['phase'])
        self.assertEqual([],self.state(student)['available_questions'])
        self.assertEqual('最後公布',self.state(student)['references']['2'])
        self.assertEqual(6,self.account('assistant','leaderboard',course=self.course)['rows'][0]['score'])
        with patch('quiz_service.time.time',return_value=deadline+1):
            self.s.tick()
        final=self.state(student)
        self.assertEqual('results',final['phase'])
        self.assertEqual(('甲',6,1),tuple(final['scoreboard'][0][k] for k in ('group_name','score','rank')))
        self.assertEqual({'group_name':'甲'},final['results'][0]['winner'])
        self.s.review(self.teacher,self.aid,choice_answer['id'],'pending',2)
        self.assertEqual('pending',self.state(student)['report'][1]['verdict'])
        self.assertIsNone(self.state(student)['results'][0]['winner'])
        self.assertEqual(0,self.state(student)['own_score']['total'])

    def test_revocation_is_per_course_and_preserves_authorship(self):
        other=self.account('teacher','create-course',title='英文')['course']
        self.account('teacher','assistant',course=other,uid='assistant')
        for course in [other,self.course]:
            self.assertEqual(self.account('teacher','leaderboard',course=course),self.account('assistant','leaderboard',course=course))
        self.s.transition(self.teacher,self.aid,'active')
        self.s.submit(self.students[0],self.aid,'2','文字')
        self.s.close_question(self.teacher,self.aid,'2')
        answer=self.selections('2')[0]['id']
        self.s.review(self.assistant,self.aid,answer,'correct',0)
        args=dict(course=self.course,uid='assistant',confirmed=True)
        with self.assertRaises(QuizError):
            self.account('assistant','remove-assistant',**args)
        with self.assertRaises(QuizError):
            self.account('teacher','remove-assistant',**dict(args,confirmed=False))
        self.account('teacher','remove-assistant',**args)
        with self.assertRaises(QuizError): self.account('assistant','leaderboard',course=self.course)
        with self.assertRaises(QuizError): self.s.review(self.assistant,self.aid,answer,'pending',1)
        with self.assertRaises(QuizError): self.s.review_history(self.assistant,self.aid)
        self.assertEqual([],self.account('teacher','course',course=self.course,staff=True)['assistants'])
        self.assertEqual([],self.account('assistant','leaderboard',course=other)['rows'])
        self.assertEqual('assistant@example.org',self.state(self.teacher)['answers'][0]['reviews'][0]['email'])

    def test_staff_ranking_request_cannot_fall_back_to_student_after_removal(self):
        self.account('assistant','create-team',course=self.course,name='第四組',password='class123')
        self.account('teacher','remove-assistant',course=self.course,uid='assistant',confirmed=True)
        with self.assertRaises(QuizError):
            self.account('assistant','leaderboard',course=self.course,staff=True)
        self.assertEqual(4,len(self.account('assistant','leaderboard',course=self.course,staff=False)['rows']))

    def test_upgrade_keeps_original_session_and_existing_grades(self):
        self.s.transition(self.teacher,self.aid,'active')
        self.s.submit(self.students[0],self.aid,'2','答案',2)
        self.s.transition(self.teacher,self.aid,'results')
        batch=self.s.review_batch(self.teacher,self.aid,'2',self.selections('2'),'correct')['batch_id']
        self.s.close()
        # Recreate the pre-change schema with a populated activity, a signed grade, and a session-owned batch.
        with sqlite3.connect(self.path) as db:
            for table,columns in [('question_meta',['closed_at']),('grade_log',['previous_verdict']),
                                  ('review_batches',['owner_uid','created_at','question','verdict','kind'])]:
                for col in columns:
                    db.execute(f'ALTER TABLE {table} DROP COLUMN {col}')
        db.close()
        self.connect()
        self.assertEqual(6,self.state(self.students[0])['own_score']['total'])
        self.assertEqual('teacher@example.org',self.state(self.teacher)['answers'][0]['reviews'][0]['email'])
        other_session=self.room('teacher')
        self.assertEqual([],self.s.review_history(other_session,self.aid)['batches'])
        with self.assertRaises(QuizError): self.s.undo_review_batch(other_session,self.aid,batch)
        legacy=self.s.review_history(self.teacher,self.aid)['batches'][0]
        self.assertIsNone(legacy['created_at'])
        self.s.undo_review_batch(self.teacher,self.aid,batch)
        self.assertEqual(0,self.state(self.students[0])['own_score']['total'])

    def test_explicit_group_validation_is_atomic(self):
        questions=['A','B','1.1']
        aid=self.s.create(self.teacher,'自訂題號',questions)['id']
        self.assertEqual({q:[q] for q in questions},self.s._units(aid))
        count=len(self.s.activities(self.teacher))
        for groups in [[{'id':'1.1','questions':['A','B']}],[{'id':'1','questions':['A','A']}],
                       [{'id':'1','questions':['A','B']},{'id':'2','questions':['A','1.1']}]]:
            with self.assertRaises(QuizError):
                self.s.create(self.teacher,'無效',questions,groups=groups)
        self.assertEqual(count,len(self.s.activities(self.teacher)))
