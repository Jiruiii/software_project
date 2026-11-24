"""Opt-in real Google acceptance: creates only a new, private test workbook.

Uses the application's HTTP routes and OAuth implementation. User consent is
interactive. Tokens stay in memory; this script never runs during unittest.
"""
import copy
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import make_server
from google_sheets import API, GoogleConnection, SheetsWorkflow, fetch_bytes
from guided_notes import SINGLE_TEMPLATE, GROUP_TEMPLATE, a1
from quiz_service import QuizService, QuizError

OUTPUT = ROOT / "output" / "live-sheets"
# Request stored formatting, not volatile calculated/display values.
FIELDS = ("spreadsheetId,properties,sheets(properties,merges,conditionalFormats,"
          "bandedRanges,basicFilter,data(startRow,startColumn,rowMetadata,"
          "columnMetadata,rowData(values(userEnteredValue,userEnteredFormat,"
          "note,textFormatRuns,dataValidation))))")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def cells(sheet):
    result = {}
    for block in sheet.get("data", []):
        for r, row in enumerate(block.get("rowData", []), block.get("startRow", 0)):
            for c, cell in enumerate(row.get("values", []), block.get("startColumn", 0)):
                if cell:
                    result[(r, c)] = copy.deepcopy(cell)
    return result


def normalized(payload, ignore_values=()):
    """Compare all fetched cells/formatting and structure, allowing exact writes."""
    result = {k: v for k, v in payload.items() if k != "sheets"}
    result["sheets"] = []
    for sheet in payload.get("sheets", []):
        sid = sheet["properties"]["sheetId"]
        entry = {k: v for k, v in sheet.items() if k != "data"}
        values = cells(sheet)
        for sheet_id, r, c in ignore_values:
            if sheet_id == sid and (r, c) in values:
                values[(r, c)].pop("userEnteredValue", None)
        entry["cells"] = {f"{r},{c}": value for (r, c), value in values.items() if value}
        entry["dimensions"] = [
            {k: v for k, v in block.items() if k != "rowData"}
            for block in sheet.get("data", [])
            if any(k in block for k in ("rowMetadata", "columnMetadata"))
        ]
        result["sheets"].append(entry)
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Acceptance:
    def __init__(self, origin, google, owner, teacher):
        self.origin, self.google, self.owner, self.teacher = origin, google, owner, teacher
        self.sid = None

    def http(self, path, body=None, token=None, expected=200):
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (token or self.teacher)}
        request = Request(self.origin + path, headers=headers,
                          data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(request, timeout=60) as response:
                status, payload = response.status, json.load(response)
        except HTTPError as error:
            status, payload = error.code, json.load(error)
        check(status == expected, f"{path}: expected {expected}, got {status}: {payload.get('error', '')}")
        return payload

    def google_request(self, suffix, body=None):
        # Helper is used only for setup/snapshots. App export goes via real HTTP.
        headers = {"Authorization": "Bearer " + self.google.access(self.owner), "Content-Type": "application/json"}
        return json.loads(fetch_bytes(API.rstrip("/") + suffix,
                                     None if body is None else json.dumps(body).encode(), headers))

    def snapshot(self):
        return self.google_request("/" + self.sid + "?" + urlencode({"fields": FIELDS}))

    def update(self, requests):
        check(bool(self.sid) and self.sid != SINGLE_TEMPLATE, "Only the newly created workbook may be modified")
        return self.google_request("/" + self.sid + ":batchUpdate", {"requests": requests})

    def setup(self):
        template = self.google_request("/" + SINGLE_TEMPLATE + "?fields=sheets.properties")
        source_id = template["sheets"][0]["properties"]["sheetId"]
        created = self.google_request("", {"properties": {"title": "課間－自動驗收－" + datetime.now().strftime("%Y%m%d-%H%M%S")},
                                           "sheets": [{"properties": {"sheetId": 0, "title": "佔位符測試"}}]})
        self.sid = created["spreadsheetId"]
        (OUTPUT / "test-workbook.txt").write_text("https://docs.google.com/spreadsheets/d/" + self.sid + "/edit\n", encoding="utf-8")
        layouts = []
        for title, dr, dc in [("原版範本", 0, 0), ("移動列欄", 8, 3)]:
            copied = self.google_request(f"/{SINGLE_TEMPLATE}/sheets/{source_id}:copyTo", {"destinationSpreadsheetId": self.sid})
            sheet_id = copied["sheetId"]
            requests = [{"updateSheetProperties": {"properties": {"sheetId": sheet_id, "title": title}, "fields": "title"}}]
            for dimension, count in [("ROWS", dr), ("COLUMNS", dc)]:
                if count:
                    requests.append({"insertDimension": {"range": {"sheetId": sheet_id, "dimension": dimension, "startIndex": 0, "endIndex": count}, "inheritFromBefore": False}})
            self.update(requests)
            # Explicit oracle for the supplied six-question fixture, not the parser.
            targets = {str(i + 1): (r + dr, 6 + dc) for i, r in enumerate([4, 6, 8, 10, 12, 14])}
            layouts.append((title, sheet_id, targets))
        self.update([
            self.cell_update(0, 2, 15, "{{Q:B}}"), self.cell_update(0, 18, 2, "{{Q:A}}"),
            self.cell_update(0, 0, 0, "非答案內容：必須完整保留"),
            {"updateCells": {"start": {"sheetId": 0, "rowIndex": 0, "columnIndex": 1},
                             "rows": [{"values": [{"userEnteredValue": {"formulaValue": "=1+2"}, "note": "保留備註"}]}],
                             "fields": "userEnteredValue,note"}},
            {"repeatCell": {"range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 20, "startColumnIndex": 0, "endColumnIndex": 16},
                            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.9, "green": 0.95, "blue": 1},
                                                          "textFormat": {"bold": True}, "wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat"}},
        ])
        layouts.append(("佔位符測試", 0, {"A": (18, 2), "B": (2, 15)}))
        template = self.google_request('/' + GROUP_TEMPLATE + '?fields=sheets.properties')
        source_id = template['sheets'][0]['properties']['sheetId']
        for title, dr, dc in [('題組原版',0,0),('題組移動列欄',5,2)]:
            copied = self.google_request(f'/{GROUP_TEMPLATE}/sheets/{source_id}:copyTo', {'destinationSpreadsheetId':self.sid})
            sheet_id=copied['sheetId']
            requests=[{'updateSheetProperties':{'properties':{'sheetId':sheet_id,'title':title},'fields':'title'}}]
            for dimension,count in [('ROWS',dr),('COLUMNS',dc)]:
                if count: requests.append({'insertDimension':{'range':{'sheetId':sheet_id,'dimension':dimension,'startIndex':0,'endIndex':count},'inheritFromBefore':False}})
            self.update(requests)
            positions = [('1.1',4,7),('1.2',5,7),('2.1',7,7),('2.2',8,7),('3',10,6),('4',12,6)]
            layouts.append((title, sheet_id, {q: (r + dr, c + dc) for q, r, c in positions}))
        return layouts

    @staticmethod
    def cell_update(sheet_id, row, col, value):
        return {"updateCells": {"start": {"sheetId": sheet_id, "rowIndex": row, "columnIndex": col},
                                "rows": [{"values": [{"userEnteredValue": {"stringValue": value}}]}], "fields": "userEnteredValue"}}

    def activity(self, title, targets):
        preview = self.http("/api/sheets/preview", {"url": "https://docs.google.com/spreadsheets/d/" + self.sid + "/edit", "worksheet": title})
        expected = {q: a1(r, c) for q, (r, c) in targets.items()}
        check({t["question"]: t["cell"] for t in preview["targets"]} == expected, "Preview positions do not match the independently specified layout")
        return self.http("/api/sheets/import", {"preview_id": preview["preview_id"], "title": "真實雲端驗收：" + title}, expected=201)

    def round_trip(self, title, sheet_id, targets):
        activity = self.activity(title, targets)
        aid = activity["id"]
        prefix = "/api/activities/" + aid
        students = [self.http("/api/join", {"code": activity["code"], "group": "驗收組" + str(i)})["token"] for i in (1, 2)]
        self.http(prefix + "/start", {})
        expected = {}
        # Leave the last question unanswered and include an apparent formula.
        units = self.http(prefix)['units']
        for i, unit in enumerate(units[:-1]):
            answers={q:('=1+1' if i==0 else f'雲端驗收－{title}－{q}') for q in unit['questions']}
            self.http(prefix+'/bundle', {'unit':unit['id'],'answers':answers,'stake':3}, students[i%2])
            self.http(prefix+'/bundle', {'unit':unit['id'],'answers':{q:'較晚答案' for q in unit['questions']}}, students[(i+1)%2])
            expected.update({q:f'{answer}（驗收組{i%2+1}）' for q,answer in answers.items()})
        self.http(prefix + "/end", {})
        teacher = self.http(prefix)
        for student in students:
            check(self.http(prefix, token=student)["results"] == teacher["results"], "Student and teacher results differ")
        before = self.snapshot()
        exported = self.http(prefix + "/export", {})
        after = self.snapshot()
        check(exported["written"] == len(expected), "Wrong written count")
        check(exported["url"].endswith(f"/{self.sid}/edit#gid={sheet_id}"), "Export did not preserve spreadsheet/sheet identity")
        sheet = next(s for s in after["sheets"] if s["properties"]["sheetId"] == sheet_id)
        actual = cells(sheet)
        for q, answer in expected.items():
            check(actual[targets[q]]["userEnteredValue"] == {"stringValue": answer}, "Winner not written as literal text")
        ignored = [(sheet_id, *targets[q]) for q in expected]
        left, right = normalized(before, ignored), normalized(after, ignored)
        check(left == right, "Unrelated cells, unanswered cells, formats or sheet structure changed")
        self.http(prefix + "/export", {})
        check(normalized(after) == normalized(self.snapshot()), "Repeated export changed the workbook")
        return {"layout": title, "passed": True, "questions": len(targets), "written": len(expected),
                "targets": {q: a1(*rc) for q, rc in targets.items()}, "identityPreserved": True,
                "literalFormula": True, "unansweredPreserved": True, "retryUnchanged": True,
                "unrelatedContentAndFormatHashBefore": digest(left), "unrelatedContentAndFormatHashAfter": digest(right)}

    def edge_cases(self, title, sheet_id, targets):
        # No-answer export must leave the entire workbook byte-for-byte equivalent
        # in its normalized, stored-data representation.
        activity = self.activity(title, targets)
        prefix = "/api/activities/" + activity["id"]
        self.http(prefix + "/start", {})
        self.http(prefix + "/end", {})
        before = normalized(self.snapshot())
        check(self.http(prefix + "/export", {})["written"] == 0, "Empty activity wrote values")
        check(normalized(self.snapshot()) == before, "Empty export changed workbook")
        # Import first, then really move a row in our disposable workbook.
        activity = self.activity(title, targets)
        prefix = "/api/activities/" + activity["id"]
        student = self.http("/api/join", {"code": activity["code"], "group": "變動測試組"})["token"]
        self.http(prefix + "/start", {})
        unit=self.http(prefix)['units'][0]
        self.http(prefix + "/bundle", {"unit":unit['id'], "answers":{q:'不應寫入' for q in unit['questions']}}, student)
        self.http(prefix + "/end", {})
        self.update([{"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1}, "inheritFromBefore": False}}])
        before = normalized(self.snapshot())
        self.http(prefix + "/export", {}, expected=409)
        check(normalized(self.snapshot()) == before, "Rejected conflict still changed workbook")
        return {"noAnswerNoWrite": True, "movedSourceRejected": True, "rejectedExportNoWrite": True}

    def auto_round(self, title, sheet_id, targets):
        activity = self.activity(title, targets)
        prefix = '/api/activities/' + activity['id']
        self.http(prefix+'/settings', {'mode':'sequential'})
        users = [self.http('/api/join', {'code':activity['code'], 'group':name})['token'] for name in ['最快組','第二組']]
        unit = self.http(prefix)['units'][0]
        first = {q:'最快－'+q for q in unit['questions']}
        second = {q:'第二快－'+q for q in unit['questions']}
        before = self.snapshot()
        original = cells(next(s for s in before['sheets'] if s['properties']['sheetId']==sheet_id))
        expected_original = {q:original.get(targets[q],{}).get('userEnteredValue',{}).get('stringValue','') for q in unit['questions']}
        def wait_for(values, previous=0):
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                state=self.http(prefix)
                sync=state['source']['sync']
                if sync['state'] in ('error','needs_auth'): raise AssertionError(sync['message'])
                if sync['state']=='synced' and (state['source']['exported_at'] or 0)>previous:
                    after=self.snapshot()
                    actual=cells(next(s for s in after['sheets'] if s['properties']['sheetId']==sheet_id))
                    for q,value in values.items():
                        check(actual.get(targets[q],{}).get('userEnteredValue',{}).get('stringValue','')==value,'Auto sync cell mismatch')
                    ignored=[(sheet_id,*targets[q]) for q in unit['questions']]
                    check(normalized(before,ignored)==normalized(after,ignored),'Auto sync changed unrelated cells or formatting')
                    # Pace the acceptance harness's extra read-back calls so
                    # two layouts do not exhaust the per-minute Google quota.
                    time.sleep(4)
                    return state
                time.sleep(.5)
            raise AssertionError('Automatic round sync timed out')
        self.http(prefix+'/start', {})
        self.http(prefix+'/bundle', {'unit':unit['id'],'answers':first,'stake':3}, users[0])
        self.http(prefix+'/bundle', {'unit':unit['id'],'answers':second,'stake':2}, users[1])
        check(normalized(before)==normalized(self.snapshot()),'Open round wrote answers early')
        self.http(prefix+'/round', {'action':'close'})
        first={q:value+'（最快組）' for q,value in first.items()}
        state=wait_for(first)
        q=unit['questions'][0]
        ids=[next(a['id'] for a in state['answers'] if a['group_name']==name and a['question_id']==q) for name in ['最快組','第二組']]
        fallback={**first,q:second[q]+'（第二組）'}
        restored={**first,q:expected_original[q]}
        for answer_id,verdict,expected in [(ids[0],'incorrect',fallback),(ids[1],'incorrect',restored),(ids[0],'correct',first)]:
            previous=state['source']['exported_at']
            self.http(prefix+'/review', {'answer_id':answer_id,'verdict':verdict})
            state=wait_for(expected,previous)
        teacher_answer='=老師正確答案－'+q
        previous=state['source']['exported_at']
        self.http(prefix+'/reference', {'question':q,'answer':teacher_answer,'override':True})
        state=wait_for({**first,q:teacher_answer+'（老師答案）'},previous)
        previous=state['source']['exported_at']
        self.http(prefix+'/reference', {'question':q,'answer':teacher_answer,'override':False})
        state=wait_for(first,previous)
        previous=state['source']['exported_at']
        self.http(prefix+'/review', {'answer_id':ids[0],'verdict':'incorrect'})
        state=wait_for(restored,previous)
        previous=state['source']['exported_at']
        self.http(prefix+'/reference', {'question':q,'answer':teacher_answer,'override':True})
        state=wait_for({**first,q:teacher_answer+'（老師答案）'},previous)
        previous=state['source']['exported_at']
        self.http(prefix+'/reference', {'question':q,'answer':'','override':False})
        state=wait_for(restored,previous)
        return {'layout':title,'passed':True,'closedRoundOnly':True,'fallback':True,'restoreWhenAllWrong':True,'regradeRestoredFirst':True,'teacherOverride':True,'cancelRestoresWinner':True,'teacherWhenAllWrong':True,'clearRestoresOriginal':True,'unrelatedCellsAndFormatsPreserved':True,'grouped':len(unit['questions'])>1}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--auto-sync-only',action='store_true')
    args=parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"timestampUtc": datetime.now(timezone.utc).isoformat(), "passed": False,
              "scope": "Real Google API; new private test workbook only; real application HTTP routes", "layouts": []}
    path = OUTPUT / "report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    password = secrets.token_urlsafe(24)
    service = QuizService(":memory:", password)
    google = GoogleConnection()
    server = thread = acceptance = None
    try:
        google.config()
        server = make_server(service, 0, SheetsWorkflow(service, google))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        acceptance = Acceptance(origin, google, None, "")
        teacher = acceptance.http("/api/teacher/login", {"password": password})["token"]
        acceptance.teacher = teacher
        acceptance.owner = service.teacher_key(teacher)
        url = acceptance.http("/api/google/connect", {})["url"]
        print("請在開啟的 Google 頁面完成授權。接著會自動建立一份專用測試表並執行驗收。", flush=True)
        check(webbrowser.open(url), "無法開啟瀏覽器，請在有桌面瀏覽器的電腦執行。")
        deadline = time.monotonic() + 600
        while not google.status(acceptance.owner)["connected"]:
            if time.monotonic() > deadline:
                raise AssertionError("等待 Google 授權逾時；尚未建立測試表。請重新執行。")
            time.sleep(0.5)
        print("Google 已授權，建立測試表並複製官方單題範本……", flush=True)
        layouts = acceptance.setup()
        selected = [layouts[0], layouts[-1]] if args.auto_sync_only else layouts
        for title, sheet_id, targets in selected:
            print("驗收：" + title, flush=True)
            report["layouts"].append(acceptance.auto_round(title, sheet_id, targets) if args.auto_sync_only else acceptance.round_trip(title, sheet_id, targets))
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        # Header-based sheets remain re-importable after answers replace blanks.
        # Marker-only sheets intentionally lose answered markers on writeback.
        if not args.auto_sync_only: report["edgeCases"] = acceptance.edge_cases(*layouts[0])
        report["passed"] = True
        print("真實 Google 驗收全部通過。測試表連結位於 output/live-sheets/test-workbook.txt。", flush=True)
        return 0
    except (QuizError, AssertionError) as error:
        report["error"] = str(error)
        print("驗收尚未通過：" + str(error), flush=True)
        return 1
    except Exception as error:
        # Avoid dumping request objects, credentials or authorization headers.
        report["error"] = type(error).__name__
        print("驗收尚未通過：" + type(error).__name__, flush=True)
        return 1
    finally:
        report["finishedUtc"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if acceptance and acceptance.owner:
            google.disconnect(acceptance.owner)
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=10)
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
