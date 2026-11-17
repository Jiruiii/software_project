"""Isolated browser acceptance for extensions; does not access Google."""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import make_server
from quiz_service import QuizService
from google_sheets import GoogleConnection, SheetsWorkflow
from guided_notes import from_xlsx, parse_grid


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['extras','question-types','teacher-ui'],default='extras')
    suite=parser.parse_args().suite
    output = ROOT/"output/playwright"; output.mkdir(parents=True, exist_ok=True)
    service = QuizService(":memory:", "extras-test-only")
    teacher=service.login('extras-test-only')['token']
    source=parse_grid(from_xlsx((ROOT/'tests/fixtures/grouped.xlsx').read_bytes())[0]); source['spreadsheet_id']='test-grouped-browser-id-1234'
    service.create_from_source(teacher,'題組驗收',source)
    service.logout(teacher)
    server = make_server(service, 0, SheetsWorkflow(service, GoogleConnection(ROOT/"tmp/not-configured-extras.json")))
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
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["passed"] else 1
    finally:
        run("close")
        server.shutdown(); thread.join(); server.server_close(); service.close()
        (output/f"{suite}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": raise SystemExit(main())
