import copy
import hashlib
import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from google_sheets import GoogleConnection, SheetsWorkflow, SCOPE
from guided_notes import SINGLE_TEMPLATE, Grid, a1, fingerprint, from_google, from_xlsx, parse_grid
from quiz_service import QuizService, QuizError
from test_guided_notes import single, payload

COPY_ID = "test-copy-spreadsheet-id-123"
COPY_URL = "https://docs.google.com/spreadsheets/d/"+COPY_ID+"/edit"


class FakeGoogle:
    """In-memory REST fixture. This is not a real Google write."""
    def __init__(self):
        self.data = payload(single()); self.writes=[]; self.fail=False; self.ignore=False

    def read(self, owner, sid): return from_google(copy.deepcopy(self.data))
    def status(self, owner): return {'configured':True, 'connected':True}
    def disconnect(self, owner): return {'ok':True}

    def request(self, owner, sid, body=None):
        if body is None: return copy.deepcopy(self.data)
        if self.fail: raise QuizError(403,"Google 權限不足")
        self.writes.append((sid,copy.deepcopy(body)))
        if not self.ignore:
            for req in body["requests"]:
                update=req["updateCells"]; start=update["start"]
                sheet=next(s for s in self.data["sheets"] if s["properties"]["sheetId"]==start["sheetId"])
                cells=sheet["data"][0]["rowData"][start["rowIndex"]]["values"]
                while len(cells) <= start["columnIndex"]:
                    cells.append({})
                cell=cells[start["columnIndex"]]
                # Respect the real Sheets field mask, preserving format/note.
                if update["fields"] != "userEnteredValue": raise AssertionError("unsafe fields")
                cell["userEnteredValue"]=copy.deepcopy(update["rows"][0]["values"][0]["userEnteredValue"])
        return {"spreadsheetId":sid,"replies":[]}


class SheetsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.service=QuizService(":memory:","test-password")
        self.teacher=self.service.login("test-password")["token"]
        self.google=FakeGoogle(); self.flow=SheetsWorkflow(self.service,self.google)

    def tearDown(self): self.service.close()

    def imported(self, url=COPY_URL):
        preview=self.flow.preview(self.teacher,url)
        return self.flow.import_activity(self.teacher,preview["preview_id"],"匯入測試")

    def ended(self, answer=True, url=COPY_URL):
        a=self.imported(url)
        student=self.service.join(a["code"],"A")["token"]
        self.service.transition(self.teacher,a["id"],"active")
        if answer: self.service.submit(student,a["id"],"1","=SUM(A1:A2)")
        self.service.transition(self.teacher,a["id"],"results")
        return a,student

    def test_regrade_exports_current_winner_and_restores_original(self):
        a, student = self.ended()
        aid = a['id']; self.flow.export(self.teacher, aid)
        answer = self.service.snapshot(self.teacher, aid)['answers'][0]
        self.service.review(self.teacher, aid, answer['id'], 'incorrect')
        self.assertTrue(self.service.snapshot(self.teacher, aid)['source']['export_stale'])
        self.flow.export(self.teacher, aid)
        self.assertEqual('', from_google(self.google.data)[0].value(4,6))
        self.service.review(self.teacher, aid, answer['id'], 'correct')
        self.flow.export(self.teacher, aid)
        self.assertEqual('=SUM(A1:A2)（A）', from_google(self.google.data)[0].value(4,6))

    def test_grouped_import_writeback_and_reimport(self):
        grid=from_xlsx((Path(__file__).parent/'fixtures/grouped.xlsx').read_bytes())[0]
        grid.cells[4,7] = '匯入時的原值'
        self.google.data=payload(grid)
        preview=self.flow.preview(self.teacher,COPY_URL)
        self.assertEqual(['H5','H6','H8','H9','G11','G13'], [t['cell'] for t in preview['targets']])
        a=self.flow.import_activity(self.teacher,preview['preview_id'],'題組'); aid=a['id']
        student=self.service.join(a['code'],'group')['token']
        self.service.transition(self.teacher,aid,'active')
        self.service.submit_unit(student,aid,'1',{'1.1':'first','1.2':'second'},3)
        self.service.transition(self.teacher,aid,'results')
        self.assertEqual(2,self.flow.export(self.teacher,aid)['written'])
        after=from_google(self.google.data)[0]
        self.assertEqual('first（group）',after.value(4,7)); self.assertEqual('second（group）',after.value(5,7))
        self.assertEqual([grid.value(r,6) for r in (4,5)], [after.value(r,6) for r in (4,5)])
        imported=self.imported()
        self.assertEqual(['1.1','1.2'],self.service.snapshot(self.teacher,imported['id'])['units'][0]['questions'])
        answer = self.service.snapshot(self.teacher,aid)['answers'][0]
        self.service.review(self.teacher,aid,answer['id'],'incorrect')
        self.flow.export(self.teacher,aid)
        self.assertEqual({**grid.cells, (5,7):'second（group）'}, from_google(self.google.data)[0].cells)

    def test_legacy_group_export_stops_before_recovering_or_writing_labels(self):
        grid = from_xlsx((Path(__file__).parent/'fixtures/grouped.xlsx').read_bytes())[0]
        source = parse_grid(grid)
        del source['layout_version']
        for t in source['targets']:
            if t['unit'] != t['question']:
                t.update(col=6, cell=a1(t['row'],6), original=grid.value(t['row'],6))
        source.update(spreadsheet_id=COPY_ID, fingerprint=fingerprint(grid,source['targets']))
        source['pending_export'] = {'sheet_id':0,'expected':{'1.1':'舊答案'},'previous':{'1.1':grid.value(4,6)}}
        grid.cells[4,6] = '舊答案'
        self.google.data = payload(grid)
        activity = self.service.create_from_source(self.teacher,'舊活動',source)
        aid = activity['id']
        self.service.transition(self.teacher,aid,'active')
        self.service.transition(self.teacher,aid,'results')
        with self.assertRaisesRegex(QuizError,'重新預覽'): self.flow.export(self.teacher,aid)
        self.assertEqual([],self.google.writes)
        self.assertEqual(source['pending_export'], self.service.export_context(self.teacher,aid)[0]['pending_export'])

    def test_judgment_during_export_requires_retry(self):
        a,_=self.ended(); aid=a['id']; answer=self.service.snapshot(self.teacher,aid)['answers'][0]
        request=self.google.request
        def raced(owner,sid,body=None):
            result=request(owner,sid,body)
            if body: self.service.review(self.teacher,aid,answer['id'],'incorrect')
            return result
        self.google.request=raced
        with self.assertRaisesRegex(QuizError,'判定已改變'): self.flow.export(self.teacher,aid)
        self.assertTrue(self.service.snapshot(self.teacher,aid)['source']['export_stale'])
        self.google.request=request; self.flow.export(self.teacher,aid)
        self.assertEqual('',from_google(self.google.data)[0].value(4,6))

    def test_preview_import_privacy_and_atomic_failure(self):
        preview=self.flow.preview(self.teacher,COPY_URL)
        self.assertEqual(6,preview["count"])
        self.assertEqual([],self.service.activities(self.teacher))
        with self.assertRaises(QuizError): self.flow.import_activity(self.teacher,preview["preview_id"],"")
        self.assertEqual([],self.service.activities(self.teacher))
        a=self.flow.import_activity(self.teacher,preview["preview_id"],"test")
        self.assertEqual([str(i) for i in range(1,7)], self.service.snapshot(self.teacher,a["id"])["questions"])
        student=self.service.join(a["code"],"A")["token"]
        self.assertNotIn("source",self.service.snapshot(student,a["id"]))
        for fn,args in [(self.flow.preview,(student,COPY_URL)),(self.flow.export,(student,a["id"])),(self.flow.import_activity,(student,preview["preview_id"],"bad"))]:
            with self.assertRaises(QuizError): fn(*args)
        with self.assertRaises(QuizError): self.flow.import_activity(self.teacher,preview["preview_id"],"reuse")

    def test_preview_owner_expiry_and_source_change(self):
        p=self.flow.preview(self.teacher,COPY_URL); key=p["preview_id"]
        other=self.service.login("test-password")["token"]
        with self.assertRaises(QuizError): self.flow.import_activity(other,key,"wrong owner")
        self.google.data["sheets"][0]["data"][0]["rowData"][4]["values"][2]["userEnteredValue"]={"stringValue":"edited"}
        with self.assertRaisesRegex(QuizError,"已改動"): self.flow.import_activity(self.teacher,key,"changed")
        self.flow.previews[key]["expires"]=0
        with self.assertRaisesRegex(QuizError,"失效"): self.flow.import_activity(self.teacher,key,"expired")
        self.assertEqual([],self.service.activities(self.teacher))

    def test_multi_sheet_selection(self):
        second=copy.deepcopy(self.google.data["sheets"][0]); second["properties"]["title"]="另一張"
        self.google.data["sheets"].append(second)
        self.assertTrue(self.flow.preview(self.teacher,COPY_URL)["needs_selection"])
        self.assertEqual(6,self.flow.preview(self.teacher,COPY_URL,"另一張")["count"])

    def test_export_original_sheet_literal_and_format_preserved_retry(self):
        a,_=self.ended(); before=copy.deepcopy(self.google.data)
        self.assertEqual(1,self.flow.export(self.teacher,a["id"])["written"])
        self.assertEqual(COPY_ID,self.google.writes[0][0])
        before["sheets"][0]["data"][0]["rowData"][4]["values"][6]["userEnteredValue"]={"stringValue":"=SUM(A1:A2)（A）"}
        self.assertEqual(before,self.google.data)
        self.assertTrue(self.service.snapshot(self.teacher,a["id"])["source"]["exported_at"])
        self.assertEqual(1,self.flow.export(self.teacher,a["id"])["written"])

    def test_export_failure_or_unverified_write_not_recorded(self):
        a,_=self.ended(); self.google.fail=True
        with self.assertRaises(QuizError): self.flow.export(self.teacher,a["id"])
        self.assertIsNone(self.service.snapshot(self.teacher,a["id"])["source"]["exported_at"])
        self.google.fail=False; self.google.ignore=True
        with self.assertRaisesRegex(QuizError,"核對失敗"): self.flow.export(self.teacher,a["id"])
        self.assertIsNone(self.service.snapshot(self.teacher,a["id"])["source"]["exported_at"])

    def test_no_answers_no_write_and_official_protection(self):
        a,_=self.ended(False)
        self.assertEqual(0,self.flow.export(self.teacher,a["id"])["written"])
        self.assertFalse(self.google.writes)
        b,_=self.ended(url="https://docs.google.com/spreadsheets/d/"+SINGLE_TEMPLATE+"/edit")
        with self.assertRaisesRegex(QuizError,"官方範本"): self.flow.export(self.teacher,b["id"])
        self.assertFalse(self.google.writes)

    def test_conflict_prevents_any_write(self):
        a,_=self.ended()
        self.google.data["sheets"][0]["data"][0]["rowData"][4]["values"][6]["userEnteredValue"]={"stringValue":"manual"}
        with self.assertRaisesRegex(QuizError,"已被修改"): self.flow.export(self.teacher,a["id"])
        self.assertFalse(self.google.writes)

    def test_shifted_layout_round_trip(self):
        grid=single()
        moved=Grid(grid.title,{(r+8,c+3):v for (r,c),v in grid.cells.items()},
                   [(r1+8,c1+3,r2+8,c2+3) for r1,c1,r2,c2 in grid.merges],42)
        self.google.data=payload(moved)
        a,_=self.ended()
        self.assertEqual(1,self.flow.export(self.teacher,a["id"])["written"])
        update=self.google.writes[0][1]["requests"][0]["updateCells"]
        self.assertEqual({"sheetId":42,"rowIndex":12,"columnIndex":9},update["start"])
        self.assertEqual("=SUM(A1:A2)（A）",from_google(self.google.data)[0].cells[(12,9)])

    def test_read_permission_failure_creates_no_activity(self):
        def denied(*args): raise QuizError(403,"來源無讀取權限")
        self.google.read=denied
        with self.assertRaisesRegex(QuizError,"讀取權限"): self.flow.preview(self.teacher,COPY_URL)
        self.assertEqual([],self.service.activities(self.teacher))


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/"client.json"
        self.path.write_text(json.dumps({"installed":{"client_id":"test.apps.googleusercontent.com","client_secret":"synthetic-secret"}}))
        self.calls=[]
        def transport(url,body,headers):
            self.calls.append((url,parse_qs(body.decode()),headers))
            return json.dumps({"access_token":"synthetic-access","refresh_token":"synthetic-refresh","expires_in":3600,"scope":SCOPE}).encode()
        self.google=GoogleConnection(self.path,transport)

    def tearDown(self): self.temp.cleanup()

    def start(self,owner="teacher"):
        return parse_qs(urlsplit(self.google.start(owner,"http://127.0.0.1:8765")["url"]).query)

    def test_pkce_state_single_use_and_no_secret_in_browser(self):
        query=self.start(); state=query["state"][0]
        self.assertEqual(["S256"],query["code_challenge_method"])
        self.assertNotIn("client_secret",query)
        verifier=self.google.pending[state]["verifier"]
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.assertEqual([challenge],query["code_challenge"])
        self.google.finish(state,"test-code",None,lambda owner:True)
        self.assertEqual([verifier],self.calls[0][1]["code_verifier"])
        self.assertEqual({"configured":True,"connected":True},self.google.status("teacher"))
        self.assertEqual("synthetic-access",self.google.access("teacher"))
        self.assertFalse(self.google.status("other")["connected"])
        with self.assertRaises(QuizError): self.google.finish(state,"test-code",None,lambda owner:True)

    def test_expiry_cancel_invalid_state_and_logged_out_owner(self):
        for variant in ["expired","cancel","logout","bad"]:
            state=self.start()["state"][0]
            if variant=="expired": self.google.pending[state]["expires"]=0
            with self.assertRaises(QuizError):
                self.google.finish("wrong" if variant=="bad" else state,"code","denied" if variant=="cancel" else None,lambda owner:variant!="logout")
        self.assertFalse(self.calls)

    def test_refresh_disconnect_missing_configuration(self):
        self.google.finish(self.start()["state"][0],"code",None,lambda owner:True)
        self.google.grants["teacher"]["expires_at"]=0
        self.assertEqual("synthetic-access",self.google.access("teacher"))
        self.assertEqual(["refresh_token"],self.calls[-1][1]["grant_type"])
        state=self.start()["state"][0]; self.google.disconnect("teacher")
        self.assertNotIn(state,self.google.pending)
        with self.assertRaises(QuizError): self.google.access("teacher")
        self.path.unlink()
        self.assertFalse(self.google.status("teacher")["configured"])
        with self.assertRaises(QuizError): self.google.start("teacher","http://127.0.0.1:8765")

    def test_rest_request_contract(self):
        self.google.finish(self.start()["state"][0],"code",None,lambda owner:True)
        calls=[]
        def transport(url,body=None,headers=None):
            calls.append((url,body,headers)); return json.dumps(payload(single())).encode()
        self.google.transport=transport
        self.assertEqual(6,len(self.google.read("teacher",COPY_ID)[0].cells.keys() & {(4,1),(6,1),(8,1),(10,1),(12,1),(14,1)}))
        self.assertIn("sheets.googleapis.com/v4/spreadsheets/"+COPY_ID,calls[0][0])
        fields=parse_qs(urlsplit(calls[0][0]).query)["fields"][0]
        self.assertIn("userEnteredValue",fields)
        self.assertNotIn("synthetic-access",calls[0][0])
        self.assertEqual("Bearer synthetic-access",calls[0][2]["Authorization"])
        self.google.request("teacher",COPY_ID,{"requests":[]})
        self.assertTrue(calls[-1][0].endswith(COPY_ID+":batchUpdate"))
        self.assertEqual({"requests":[]},json.loads(calls[-1][1]))


if __name__ == "__main__": unittest.main()
