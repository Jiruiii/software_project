import json
import unittest
from unittest.mock import patch

import test_sheet_auto_sync as sync_tests


class RoundReferenceTests(unittest.TestCase):
    setUp=sync_tests.AutoSyncTests.setUp
    tearDown=sync_tests.AutoSyncTests.tearDown
    close_first=sync_tests.AutoSyncTests.close_first
    value=sync_tests.AutoSyncTests.value
    state=sync_tests.AutoSyncTests.state

    def test_sequential_publish_update_clear_and_unanswered(self):
        self.close_first()
        late=self.s.join(self.a['code'],'未作答組')['token']
        self.s.reference(self.t,self.aid,'1','<b>老師答案</b>\n第二行')
        self.s.db.execute("UPDATE question_meta SET reference_answer='future secret' WHERE activity_id=? AND question_id='2'",(self.aid,));self.s.db.commit()
        for student in [self.u,self.v,late]:
            state=self.s.snapshot(student,self.aid)
            self.assertEqual({'1':'<b>老師答案</b>\n第二行'},state['references'])
            self.assertNotIn('reference_overrides',state)
            self.assertNotIn('correct_index',state['question_settings']['1'])
        self.s.round_action(self.t,self.aid,'next')
        self.assertEqual({'1':'<b>老師答案</b>\n第二行'},self.s.snapshot(late,self.aid)['references'])
        self.s.reference(self.t,self.aid,'1','updated')
        self.assertEqual('updated',self.s.snapshot(late,self.aid)['references']['1'])
        self.s.reference(self.t,self.aid,'1','')
        self.assertEqual('',self.s.snapshot(late,self.aid)['references']['1'])

    def test_all_mode_until_timer_end(self):
        self.s.db.execute("UPDATE question_meta SET reference_answer='hidden' WHERE activity_id=?",(self.aid,));self.s.db.commit()
        self.assertEqual({},self.s.snapshot(self.u,self.aid)['references'])
        self.s.configure(self.t,self.aid,'all',duration_seconds=2)
        with patch('quiz_service.time.time',return_value=1000) as clock:
            self.s.transition(self.t,self.aid,'active')
            self.assertEqual({},self.s.snapshot(self.u,self.aid)['references'])
            clock.return_value=1002
            self.assertEqual('hidden',self.s.snapshot(self.u,self.aid)['references']['1'])

    def test_identical_answer_fallback_changes_source_only(self):
        self.s.configure(self.t,self.aid,'sequential');self.s.transition(self.t,self.aid,'active')
        self.s.submit(self.u,self.aid,'1','=same',2);self.s.submit(self.v,self.aid,'1','=same',3)
        self.s.round_action(self.t,self.aid,'close');self.auto.run_once()
        self.assertEqual('=same（A）',self.value())
        first=self.s.snapshot(self.t,self.aid)['answers'][0]
        self.s.review(self.t,self.aid,first['id'],'incorrect');self.auto.run_once()
        self.assertEqual('=same（B）',self.value())
        self.s.reference(self.t,self.aid,'1','=same',True);self.auto.run_once()
        self.assertEqual('=same（老師答案）',self.value())
        self.s.reference(self.t,self.aid,'1','=same',False);self.auto.run_once()
        self.assertEqual('=same（B）',self.value())
        self.assertEqual(['=same','=same'],[a['text'] for a in self.s.snapshot(self.t,self.aid)['answers']])
        self.assertEqual('=same',self.s.snapshot(self.t,self.aid)['references']['1'])

    def test_legacy_unannotated_export_is_safely_updated(self):
        self.close_first()
        source=json.loads(self.s.db.execute('SELECT source_json FROM sheet_sources').fetchone()[0])
        source['last_export']={'1':'=first'}
        self.s.db.execute('UPDATE sheet_sources SET source_json=?',(json.dumps(source),));self.s.db.commit()
        self.g.data['sheets'][0]['data'][0]['rowData'][4]['values'][6]['userEnteredValue']={'stringValue':'=first'}
        self.auto.watch(self.t,self.aid,retry=True);self.auto.run_once()
        self.assertEqual('=first（A）',self.value())
        self.s.review(self.t,self.aid,self.ids[0],'incorrect');self.s.review(self.t,self.aid,self.ids[1],'incorrect');self.auto.run_once()
        self.assertEqual('',self.value())
