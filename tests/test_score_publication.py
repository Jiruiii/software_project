import json
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from app import make_server
from quiz_service import QuizService


class ScorePublicationTests(unittest.TestCase):
    def setUp(self):
        self.s = QuizService(':memory:', 'test')
        self.t = self.s.login('test')['token']
        self.a = self.s.create(self.t, '公布時機', ['1', '2'])
        self.aid = self.a['id']
        self.u = self.s.join(self.a['code'], 'A')['token']
        self.v = self.s.join(self.a['code'], 'B')['token']
        self.s.question_settings(self.t, self.aid, '1', True,
                                 [{'question':'1', 'type':'choice', 'options':['yes','no'], 'correct_index':0}])

    def tearDown(self): self.s.close()

    def test_live_top_five_counts_only_published_points_in_this_activity(self):
        def top():
            rows = self.s.snapshot(self.u, self.aid)['top_five']
            self.assertTrue(all(set(row) == {'rank', 'group_name', 'score'} for row in rows))
            return [(row['rank'], row['group_name'], row['score']) for row in rows]

        self.assertNotIn('top_five', self.s.snapshot(self.u, self.aid))
        for name in 'GFEDC':
            self.s.join(self.a['code'], name)
        self.s.configure(self.t, self.aid, 'sequential')
        self.s.transition(self.t, self.aid, 'active')
        self.s.submit(self.u, self.aid, '1', 'yes', 1)
        self.s.submit(self.v, self.aid, '1', 'yes', 3)
        self.assertEqual(top(), [(1, name, 0) for name in 'ABCDE'])
        self.s.round_action(self.t, self.aid, 'close')
        self.assertEqual(top(), [(1, 'A', 5), (1, 'B', 5), (3, 'C', 0), (3, 'D', 0), (3, 'E', 0)])
        first = self.s.snapshot(self.t, self.aid)['answers'][0]
        self.assertEqual(self.s.snapshot(self.t, self.aid)['top_five'], self.s.snapshot(self.u, self.aid)['top_five'])
        self.s.review(self.t, self.aid, first['id'], 'incorrect')
        self.assertEqual(self.s.snapshot(self.t, self.aid)['top_five'], self.s.snapshot(self.u, self.aid)['top_five'])
        self.assertEqual(top(), [(1, 'B', 7), (2, 'C', 0), (2, 'D', 0), (2, 'E', 0), (2, 'F', 0)])
        self.s.transition(self.t, self.aid, 'results')
        self.assertNotIn('top_five', self.s.snapshot(self.u, self.aid))
        next_game = self.s.create(self.t, '下一場', ['1'])
        student = self.s.join(next_game['code'], 'B')['token']
        self.s.transition(self.t, next_game['id'], 'active')
        self.assertEqual(self.s.snapshot(student, next_game['id'])['top_five'],
                         [{'rank': 1, 'group_name': 'B', 'score': 0}])

    def test_upgrade_keeps_started_activity_on_original_rules(self):
        preparing=self.s.create(self.t,'未開始',['1'])
        self.s.transition(self.t,self.aid,'active')
        self.s.submit(self.u,self.aid,'1','yes',2)
        self.s.db.execute('ALTER TABLE activity_options DROP COLUMN speed_scoring')
        self.s._init_extras()
        self.s.transition(self.t,self.aid,'results')
        self.assertEqual({'wager':2,'speed':0,'total':2}, self.s.snapshot(self.u,self.aid)['own_points'])
        self.assertTrue(self.s.snapshot(self.t,preparing['id'])['speed_scoring'])

    def test_bonus_podium_and_promotion_after_regrade(self):
        students=[self.u,self.v]+[self.s.join(self.a['code'],name)['token'] for name in 'CDE']
        self.s.transition(self.t,self.aid,'active')
        for token,answer,stake in zip(students,['no','yes','yes','yes','yes'],[3,0,2,1,3]):
            self.s.submit(token,self.aid,'1',answer,stake)
            self.assertNotIn('points',self.s.snapshot(token,self.aid)['answers'][0])
        self.s.transition(self.t,self.aid,'results')
        def verify(expected):
            for token,(wager,speed) in zip(students,expected):
                state=self.s.snapshot(token,self.aid)
                parts={'wager':wager,'speed':speed,'total':wager+speed}
                self.assertEqual(parts,state['own_points'])
                self.assertEqual(parts,state['answers'][0]['points'])
                self.assertEqual(parts['total'],state['report'][0]['points'])
                self.assertEqual(parts['total'],next(r['score'] for r in state['scoreboard'] if r['group_name']==state['group_name']))
        verify([(-3,0),(0,4),(2,2),(1,1),(3,0)])
        first=self.s.snapshot(self.t,self.aid)['answers'][0]
        self.s.review(self.t,self.aid,first['id'],'correct')
        verify([(3,4),(0,2),(2,1),(1,0),(3,0)])

    def test_http_submit_retry_poll_and_end_hide_open_all_mode(self):
        self.s.transition(self.t, self.aid, 'active')
        server = make_server(self.s, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(action='', data=None, token=None):
            req = Request(f'http://127.0.0.1:{server.server_port}/api/activities/{self.aid}'+action,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={'Content-Type':'application/json','Authorization':'Bearer '+(token or self.u)})
            with urlopen(req, timeout=3) as response: return json.load(response)
        try:
            for token, answer in [(self.u, 'yes'), (self.v, 'no')]:
                data = {'question':'1', 'answer':answer, 'stake':3}
                first = request('/answers', data, token)
                self.assertEqual('withheld', first['verdict'])
                self.assertEqual(first, request('/answers', data, token))
                state = request(token=token)
                self.assertEqual({'total':0, 'pending_units':0, 'awaiting_close_units':1}, state['own_score'])
                self.assertEqual('withheld', state['answers'][0]['verdict'])
                for key in ['correct_index', 'scoreboard', 'results', 'groups']:
                    self.assertNotIn(key, json.dumps(state))
            request('/end', {}, self.t)
            self.assertEqual(7, request(token=self.u)['own_score']['total'])
            self.assertEqual(-3, request(token=self.v)['own_score']['total'])
            self.assertEqual('correct', request(token=self.u)['answers'][0]['verdict'])
            self.assertEqual('incorrect', request(token=self.v)['answers'][0]['verdict'])
        finally:
            server.shutdown(); thread.join(); server.server_close()

    def test_bundle_same_withheld_state_for_wrong_correct_and_pending(self):
        self.s.db.execute("UPDATE question_meta SET unit_id='1' WHERE activity_id=?", (self.aid,)); self.s.db.commit()
        self.s.configure(self.t, self.aid, 'sequential')
        self.s.transition(self.t, self.aid, 'active')
        for token, answer in [(self.u, 'yes'), (self.v, 'no')]:
            result = self.s.submit_unit(token, self.aid, '1', {'1':answer, '2':'short'}, 3)
            self.assertEqual(['withheld','withheld'], [a['verdict'] for a in result['answers']])
            self.assertEqual(result, self.s.submit_unit(token, self.aid, '1', {'1':answer, '2':'short'}, 3))
            self.assertEqual({'total':0, 'pending_units':0, 'awaiting_close_units':1}, self.s.snapshot(token, self.aid)['own_score'])
        self.s.round_action(self.t, self.aid, 'close')
        self.assertEqual({'total':0, 'pending_units':1, 'awaiting_close_units':0}, self.s.snapshot(self.u, self.aid)['own_score'])
        self.assertEqual({'total':-3, 'pending_units':0, 'awaiting_close_units':0}, self.s.snapshot(self.v, self.aid)['own_score'])

    def test_deadline_publishes_sequential_then_preserves_prior_score(self):
        self.s.configure(self.t, self.aid, 'sequential', duration_seconds=5)
        with patch('quiz_service.time.time', return_value=1000) as clock:
            self.s.transition(self.t, self.aid, 'active')
            clock.return_value = 1001
            self.s.submit(self.u, self.aid, '1', 'yes', 2)
            self.assertEqual(0, self.s.snapshot(self.u, self.aid)['own_score']['total'])
            clock.return_value = 1005
            state = self.s.snapshot(self.u, self.aid)
            self.assertEqual('active', state['phase'])
            self.assertEqual('correct', state['answers'][0]['verdict'])
            self.assertEqual(6, state['own_score']['total'])
            self.s.round_action(self.t, self.aid, 'next')
            clock.return_value = 1006
            self.s.submit(self.u, self.aid, '2', 'short', 3)
            self.assertEqual({'total':6, 'pending_units':0, 'awaiting_close_units':1}, self.s.snapshot(self.u, self.aid)['own_score'])
            clock.return_value = 1010
            state = self.s.snapshot(self.u, self.aid)
            self.assertEqual('results', state['phase'])
            self.assertEqual({'total':6, 'pending_units':1, 'awaiting_close_units':0}, state['own_score'])

    def test_all_mode_deadline_publishes_zero_stake_verdict(self):
        self.s.configure(self.t, self.aid, 'all', duration_seconds=5)
        with patch('quiz_service.time.time', return_value=1000) as clock:
            self.s.transition(self.t, self.aid, 'active')
            self.assertEqual('withheld', self.s.submit(self.u, self.aid, '1', 'no', 0)['verdict'])
            clock.return_value = 1005
            state = self.s.snapshot(self.u, self.aid)
            self.assertEqual('results', state['phase'])
            self.assertEqual('incorrect', state['answers'][0]['verdict'])
            self.assertEqual({'total':0, 'pending_units':0, 'awaiting_close_units':0}, state['own_score'])
