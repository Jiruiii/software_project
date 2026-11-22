"""Isolated browser acceptance for extensions; does not access Google."""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from unittest.mock import patch
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import make_server
from quiz_service import QuizService
from google_sheets import GoogleConnection, SheetsWorkflow
from guided_notes import from_xlsx, parse_grid


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['extras','question-types','multiple','teacher-ui','batch-review','question-timing','auto-sync','teacher-reference','review-flow','courses','cross-priority'],default='extras')
    suite=parser.parse_args().suite
    output = ROOT/"output/playwright"; output.mkdir(parents=True, exist_ok=True)
    service = QuizService(":memory:", "extras-test-only")
    teacher=service.login('extras-test-only')['token']
    source=parse_grid(from_xlsx((ROOT/'tests/fixtures/grouped.xlsx').read_bytes())[0]); source['spreadsheet_id']='test-grouped-browser-id-1234'
    service.create_from_source(teacher,'題組驗收',source)
    if suite == 'question-timing':
        activity = service.create(teacher, '逐題計時驗收', ['1', '2'])
        aid = activity['id']
        student = service.join(activity['code'], '計時A組')['token']
        service.configure(teacher, aid, 'sequential')
        origin = time.time() - 200
        with patch('quiz_service.time.time', return_value=origin) as clock:
            service.transition(teacher, aid, 'active')
            clock.return_value = origin + 3
            service.submit(student, aid, '1', '第一題答案')
            service.round_action(teacher, aid, 'close')
            clock.return_value = origin + 60
            service.round_action(teacher, aid, 'next')
            clock.return_value = origin + 62.35
            service.submit(student, aid, '2', '第二題答案')
        # Simulate an earlier legacy round whose opening was never recorded.
        service.db.execute("UPDATE answers SET elapsed_basis='activity' WHERE activity_id=? AND question_id='1'", (aid,))
        service.db.execute("UPDATE question_meta SET opened_at=NULL WHERE activity_id=? AND question_id='1'", (aid,))
        service.db.commit()
    connection = GoogleConnection(ROOT/"tmp/not-configured-extras.json")
    if suite in ('auto-sync','teacher-reference'):
        from test_google_sheets import FakeGoogle, COPY_URL
        connection = FakeGoogle()
        flow = SheetsWorkflow(service, connection)
        activity = flow.import_activity(teacher, flow.preview(teacher, COPY_URL)['preview_id'], '自動同步驗收')
        service.configure(teacher, activity['id'], 'sequential')
        service.question_settings(teacher, activity['id'], '2', True,
                                  [{'question':'2','type':'choice','options':['正解','錯誤選項'],'correct_index':0}])
    service.logout(teacher)
    if suite in ('courses', 'cross-priority'):
        from course_accounts import Courses
        from quiz_service import QuizError
        def verify_fixture(token, project):
            if token not in ('admin', 'teacher', 'student', 'assistant'):
                raise QuizError(401, '未知的測試帳號')
            return token, token+'@example.org'
        accounts = Courses(service, dict(apiKey='fixture',projectId='demo',authDomain='demo.firebaseapp.com',appId='web'), 'admin', verify_fixture)
        accounts.dispatch('teacher','home',{})
        accounts.dispatch('assistant','home',{})
        accounts.dispatch('admin','grant',{'uid':'teacher'})
    server = make_server(service, 0, SheetsWorkflow(service, connection))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx")
    if not npx: raise RuntimeError("Node.js/npx is required")
    cli = [npx, "--yes", "--package", "@playwright/cli", "playwright-cli", f"-s=extras-{os.getpid()}"]
    report = {"passed": False, "timestampUtc": datetime.now(timezone.utc).isoformat()}
    def run(*args):
        return subprocess.run(cli+list(args), cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    try:
        opened = run("open", f"http://127.0.0.1:{server.server_port}")
        if opened.returncode: raise RuntimeError(opened.stdout+opened.stderr)
        result = run("run-code", "--filename", f"tests/browser-{suite}.js")
        (output/f"{suite}-browser.log").write_text(result.stdout+result.stderr, encoding="utf-8")
        if result.returncode or "### Result\n" not in result.stdout: raise RuntimeError(f"Browser failed; see {suite}-browser.log")
        report.update(json.JSONDecoder().raw_decode(result.stdout.split("### Result\n", 1)[1].lstrip())[0])
        if suite == 'auto-sync':
            written = [r['updateCells']['rows'][0]['values'][0]['userEnteredValue']['stringValue']
                       for _, body in connection.writes for r in body['requests']]
            if written != ['最快答案（最快組）', '第二快答案（第二組）', '', '最快答案（最快組）', '正解（第二組）']:
                raise AssertionError('Unexpected sheet write sequence: '+repr(written))
            report['verifiedWriteSequence'] = written
            report['googleMode'] = 'in-memory REST fixture; no live Google write'
        if suite == 'teacher-reference':
            written = [r['updateCells']['rows'][0]['values'][0]['userEnteredValue']['stringValue'] for _, body in connection.writes for r in body['requests']]
            if written != ['學生答案（測試組）','老師正解（老師答案）','學生答案（測試組）','無人作答的正解（老師答案）']:
                raise AssertionError('Unexpected teacher reference writes: '+repr(written))
            report['verifiedWriteSequence'] = written
            report['googleMode'] = 'in-memory REST fixture; no live Google write'
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["passed"] else 1
    finally:
        run("close")
        server.shutdown(); thread.join(); server.server_close(); service.close()
        (output/f"{suite}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": raise SystemExit(main())
