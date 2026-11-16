"""One-command concurrent HTTP + browser checks; never touches the live server."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import make_server
from quiz_service import QuizService
from google_sheets import GoogleConnection, SheetsWorkflow
from test_many_groups import ManyGroupsTests


def main():
    parser=argparse.ArgumentParser(description="30-group isolated classroom verification")
    parser.add_argument("--http-only",action="store_true",help="Skip browser checks")
    args=parser.parse_args()
    os.chdir(ROOT)
    output=ROOT/"output"/"playwright"; output.mkdir(parents=True,exist_ok=True)
    report={"timestampUtc":datetime.now(timezone.utc).isoformat(),"passed":False,"http":[],"browser":None,
            "scope":"localhost simulation; no real Google access; not 30 physical devices"}
    server=service=thread=None
    temp=None
    cli=None
    try:
        ManyGroupsTests.metrics=[]
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ManyGroupsTests))
        report["http"] = ManyGroupsTests.metrics
        report["httpPassed"]=result.wasSuccessful()
        if not result.wasSuccessful(): return 1
        if not args.http_only:
            npx=shutil.which("npx.cmd" if os.name=="nt" else "npx")
            if not npx: raise RuntimeError("Node.js/npx is required for browser checks; use --http-only for HTTP checks.")
            session=f"classroom-many-{os.getpid()}"
            cli=[npx,"--yes","--package","@playwright/cli","playwright-cli",f"-s={session}"]
            temp=tempfile.TemporaryDirectory(prefix="classroom-browser-")
            service=QuizService(Path(temp.name)/"browser.sqlite3","many-groups-test-only")
            # No credentials loaded from the user's project during these tests.
            sheets=SheetsWorkflow(service,GoogleConnection(Path(temp.name)/"not-configured.json"))
            server=make_server(service,0,sheets)
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            def run(*arguments,timeout=120):
                process=subprocess.run(cli+list(arguments),cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
                return process
            opened=run("open",f"http://127.0.0.1:{server.server_port}")
            if opened.returncode: raise RuntimeError("Could not open QA browser: "+opened.stdout+opened.stderr)
            print("Running browser checks: teacher + 3 student tabs, 30 simulated groups...",flush=True)
            browser=run("run-code","--filename","tests/browser-many-groups.js",timeout=180)
            (output/"many-groups-browser.log").write_text(browser.stdout+browser.stderr,encoding="utf-8")
            if browser.returncode or "### Result\n" not in browser.stdout:
                raise RuntimeError("Browser check failed; see output/playwright/many-groups-browser.log")
            report["browser"]=json.JSONDecoder().raw_decode(browser.stdout.split("### Result\n",1)[1].lstrip())[0]
            if not report["browser"].get("passed"): raise RuntimeError("Browser checks did not pass")
        report["passed"]=True
        print(json.dumps(report,ensure_ascii=True,indent=2),flush=True)
        return 0
    except Exception as error:
        report["error"]=str(error)
        print(str(error),file=sys.stderr)
        return 1
    finally:
        if cli:
            try: subprocess.run(cli+["close"],cwd=ROOT,capture_output=True,timeout=30)
            except (OSError,subprocess.TimeoutExpired): pass
        if server: server.shutdown(); server.server_close()
        if thread: thread.join(timeout=10)
        if service: service.close()
        if temp: temp.cleanup()
        (output/"many-groups-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        browser=report.get("browser") or {}
        summary=["課堂搶答・多組自動測試結果", "整體結果："+("通過" if report["passed"] else "未通過"),
                 "執行時間（UTC）："+report["timestampUtc"],
                 "測試範圍：本機模擬，未使用真實 Google 試算表，也不是 30 台實體裝置。",
                 "同時搶答：30 組 × 6 題 × 3 輪，共 540 筆答案。",
                 "檢查項目：答案完整、唯一贏家、同組重送、結束邊界、學生隱私、各組結果一致。",
                 "HTTP 測試："+("通過" if report.get("httpPassed") else "未通過")]
        if browser:
            summary.extend(["畫面核對：老師 180 格答案，以及 3 組學生分頁；其餘學生以 HTTP 模擬。",
                            "畫面測試每題先由不同指定小組送出，再讓其餘 29 組同時送出，以核對不同贏家。",
                            f"開始同步：{browser['startSyncMs']} ms；結束同步：{browser['endSyncMs']} ms；老師答案顯示延遲：{browser['teacherDisplayLagMs']} ms。"])
            summary.extend(f"第 {w['question']} 題：{w['group']} 搶答成功" for w in browser["winners"])
        if report.get("error"): summary.append("錯誤："+report["error"])
        summary.append("詳細資料：many-groups-report.json；畫面截圖：many-groups-*.png")
        (output/"many-groups-summary.txt").write_text("\n".join(summary)+"\n",encoding="utf-8-sig")


if __name__=="__main__": raise SystemExit(main())
