"""Isolated browser acceptance for extensions; does not access Google."""
import json
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


def main():
    output = ROOT/"output/playwright"; output.mkdir(parents=True, exist_ok=True)
    service = QuizService(":memory:", "extras-test-only")
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
        result = run("run-code", "--filename", "tests/browser-extras.js")
        (output/"extras-browser.log").write_text(result.stdout+result.stderr, encoding="utf-8")
        if result.returncode or "### Result\n" not in result.stdout: raise RuntimeError("Browser failed; see extras-browser.log")
        report.update(json.JSONDecoder().raw_decode(result.stdout.split("### Result\n", 1)[1].lstrip())[0])
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["passed"] else 1
    finally:
        run("close")
        server.shutdown(); thread.join(); server.server_close(); service.close()
        (output/"extras-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": raise SystemExit(main())
