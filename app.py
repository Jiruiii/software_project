"""Loopback-only classroom web application, using Python's standard library."""
import argparse
import getpass
import html
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from quiz_service import QuizError, QuizService
from google_sheets import SheetsWorkflow

ROOT = Path(__file__).resolve().parent


def make_server(service, port=8000, sheets=None):
    sheets = sheets or SheetsWorkflow(service)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, fmt, *args):
            # Avoid logging request payloads, tokens or arbitrary URL contents.
            pass

        def respond(self, status, payload, mime="application/json; charset=utf-8", filename=None):
            body = json.dumps(payload, ensure_ascii=False).encode() if not isinstance(payload, bytes) else payload
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            host = self.headers.get("Host", "")
            expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in expected:
                raise QuizError(403, "此服務僅允許本機存取。")
            path = urlsplit(self.path).path
            if self.command == "GET" and path == "/oauth/callback":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    sheets.google.finish(query.get("state",[""])[0], query.get("code",[""])[0],
                                         query.get("error",[""])[0], service.teacher_active)
                    message, status = "Google 已連線。請回到原本的教師分頁，狀態會自動更新。", 200
                except QuizError as exc:
                    message, status = str(exc), exc.status
                body = f'<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Google 連線結果</title><link rel="stylesheet" href="/style.css"><main><h1>Google 連線</h1><p>{html.escape(message)}</p><p>可關閉此分頁。</p></main></html>'
                return self.respond(status, body.encode(), "text/html; charset=utf-8")
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                raise QuizError(403, "不允許跨來源操作。")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise QuizError(403, "不允許跨網站操作。")
            if self.command == "GET" and path in ("/", "/app.js", "/style.css", "/google-setup.html"):
                file, mime = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css"), "/google-setup.html":("google-setup.html","text/html")}[path]
                return self.respond(200, (ROOT / "public" / file).read_bytes(), mime + "; charset=utf-8")
            if self.command == "GET" and path == "/api/health":
                return self.respond(200, {"ok": True})
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            data = {}
            if self.command == "POST":
                if self.headers.get_content_type() != "application/json":
                    raise QuizError(415, "請使用 JSON 格式送出。")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise QuizError(400, "無效請求長度。")
                if not 0 < length <= 65536:
                    raise QuizError(413, "送出內容過大或為空。")
                try:
                    data = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError):
                    raise QuizError(400, "無效的 JSON 內容。")
                if not isinstance(data, dict):
                    raise QuizError(400, "送出內容必須是物件。")
            if self.command == "POST" and path == "/api/teacher/login":
                return self.respond(200, service.login(data.get("password"), self.client_address[0]))
            if self.command == "POST" and path == "/api/join":
                return self.respond(200, service.join(data.get("code"), data.get("group")))
            if self.command == "POST" and path == "/api/logout":
                if token:
                    try:
                        sheets.google.disconnect(service.teacher_key(token))
                    except QuizError:
                        pass
                return self.respond(200, service.logout(token))
            if path.startswith("/api/google/"):
                owner = service.teacher_key(token)
                if self.command == "GET" and path == "/api/google/status":
                    return self.respond(200, sheets.google.status(owner))
                if self.command == "POST" and path == "/api/google/connect":
                    return self.respond(200, sheets.google.start(owner, f"http://127.0.0.1:{self.server.server_port}"))
                if self.command == "POST" and path == "/api/google/disconnect":
                    return self.respond(200, sheets.google.disconnect(owner))
            if self.command == "POST" and path == "/api/sheets/preview":
                return self.respond(200, sheets.preview(token, data.get("url"), data.get("worksheet")))
            if self.command == "POST" and path == "/api/sheets/import":
                return self.respond(201, sheets.import_activity(token, data.get("preview_id"), data.get("title")))
            if path == "/api/activities":
                if self.command == "GET":
                    return self.respond(200, {"activities": service.activities(token)})
                if self.command == "POST":
                    return self.respond(201, service.create(token, data.get("title"), data.get("questions")))
            match = re.fullmatch(r"/api/activities/([a-f0-9]{24})(?:/(start|end|answers|export|csv|settings|round|review|clusters|reference|report|bundle))?", path)
            if match:
                aid, action = match.groups()
                if self.command == "POST" and action == "bundle":
                    return self.respond(200, service.submit_unit(token, aid, data.get("unit"), data.get("answers"), data.get("stake", 1)))
                if self.command == "POST" and action == "reference":
                    return self.respond(200, service.reference(token, aid, data.get("question"), data.get("answer")))
                if self.command == "GET" and action == "report":
                    return self.respond(200, service.report_csv(token, aid), "text/csv; charset=utf-8", "group-report.csv")
                if self.command == "POST" and action == "clusters":
                    return self.respond(200, service.clusters(token, aid, data.get("question")))
                if self.command == "POST" and action == "review":
                    return self.respond(200, service.review(token, aid, data.get("answer_id"), data.get("verdict")))
                if self.command == "POST" and action == "settings":
                    return self.respond(200, service.configure(token, aid, data.get("mode"), data.get("fairness", False), data.get("duration_seconds", 0)))
                if self.command == "POST" and action == "round":
                    return self.respond(200, service.round_action(token, aid, data.get("action")))
                if self.command == "GET" and action == "csv":
                    return self.respond(200, service.activity_csv(token, aid), "text/csv; charset=utf-8", "classroom-results.csv")
                if self.command == "GET" and action is None:
                    return self.respond(200, service.snapshot(token, aid))
                if self.command == "POST" and action in ("start", "end"):
                    return self.respond(200, service.transition(token, aid, "active" if action == "start" else "results"))
                if self.command == "POST" and action == "answers":
                    return self.respond(200, service.submit(token, aid, data.get("question"), data.get("answer"), data.get("stake", 1)))
                if self.command == "POST" and action == "export":
                    return self.respond(200, sheets.export(token, aid))
            raise QuizError(404, "找不到此頁面或操作。")

        def handle_request(self):
            try:
                self.dispatch()
            except QuizError as error:
                self.respond(error.status, {"error": str(error)})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except Exception as error:
                print(f"Server error: {type(error).__name__}", file=sys.stderr)
                self.respond(500, {"error": "伺服器處理失敗，請稍後再試。"})

        do_GET = handle_request
        do_POST = handle_request

    class TimedServer(ThreadingHTTPServer):
        def service_actions(self):
            service.tick()
    return TimedServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="課堂搶答系統（本機）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "classroom.sqlite3")
    args = parser.parse_args()
    password = os.environ.get("QUIZ_TEACHER_PASSWORD") or getpass.getpass("設定本次教師登入密碼（輸入不顯示）: ")
    if len(password) < 8:
        parser.error("教師密碼至少需要 8 個字元。")
    service = QuizService(args.db, password)
    try:
        server = make_server(service, args.port)
    except OSError:
        service.close()
        parser.error("連接埠無法使用，請改用 --port 8001，或停止原服務。")
    print(f"課堂搶答系統 http://127.0.0.1:{server.server_port} （Ctrl+C 停止）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
