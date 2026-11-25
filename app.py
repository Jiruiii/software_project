"""Loopback-only classroom web application, using Python's standard library."""
import argparse
import getpass
import html
import json
import os
import re
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from quiz_service import QuizError, QuizService
from google_sheets import ServerSheetsConnection, SheetsWorkflow
from sheet_auto_sync import SheetsAutoSync

ROOT = Path(__file__).resolve().parent


def make_server(service, port=8000, sheets=None, portal=False, public_origin=None):
    accounts = service.courses
    dns_label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if public_origin and (not accounts or not re.fullmatch(rf"https://{dns_label}(?:\.{dns_label})+", public_origin)):
        raise ValueError("雲端模式需要 Firebase 設定及完整 HTTPS 網域。")
    if not accounts and service.db.execute("SELECT 1 FROM sqlite_master WHERE name='auth_project'").fetchone():
        raise ValueError("此資料庫已啟用帳號，請載入原 Firebase 專案設定。")
    sheets = sheets or SheetsWorkflow(service)
    auto_sync = SheetsAutoSync(sheets)
    class Handler(BaseHTTPRequestHandler):
        def managed(self, result, token, aid):
            auto_sync.watch(token, aid)
            return self.respond(200, result)

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
            policy = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; img-src 'self' data:"
            if accounts and urlsplit(self.path).path in ('/', '/classroom'):
                policy += " https://*.googleusercontent.com"
            if accounts and urlsplit(self.path).path == '/':
                domain = accounts.config['authDomain']
                policy += f"; script-src 'self' https://www.gstatic.com https://apis.google.com; frame-src https://{domain}; connect-src 'self' https://*.googleapis.com https://{domain}"
            self.send_header("Content-Security-Policy", policy)
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            host = self.headers.get("Host", "")
            expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if public_origin:
                expected = {urlsplit(public_origin).netloc}
            if host not in expected:
                raise QuizError(403, "此網址未開放存取。")
            path = urlsplit(self.path).path
            if not public_origin and self.command == "GET" and path == "/oauth/callback":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    sheets.google.finish(query.get("state",[""])[0], query.get("code",[""])[0],
                                         query.get("error",[""])[0], service.teacher_active)
                    message, status = "Google 已連線。請回到原本的教師分頁，狀態會自動更新。", 200
                except QuizError as exc:
                    message, status = str(exc), exc.status
                body = f'<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Google 連線結果</title><link rel="icon" href="/favicon.ico"><link rel="stylesheet" href="/style.css"><main><h1>Google 連線</h1><p>{html.escape(message)}</p><p>可關閉此分頁。</p></main></html>'
                return self.respond(status, body.encode(), "text/html; charset=utf-8")
            origin = self.headers.get("Origin")
            if origin and origin != (public_origin or f"http://{host}"):
                raise QuizError(403, "不允許跨來源操作。")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise QuizError(403, "不允許跨網站操作。")
            if self.command == "GET" and (portal or accounts):
                files = {"/": ("courses.html", "text/html"), "/courses.js": ("courses.js", "text/javascript")}
                if accounts:
                    files["/classroom"] = ("index.html", "text/html")
                if path in files:
                    file, mime = files[path]
                    return self.respond(200, (ROOT / "public" / file).read_bytes(), mime + "; charset=utf-8")
                if path == "/api/firebase-config":
                    return self.respond(200, accounts.config if accounts else {})
            if self.command == "GET" and path == "/favicon.ico":
                return self.respond(200, (ROOT / "public" / "favicon.ico").read_bytes(), "image/vnd.microsoft.icon")
            if self.command == "GET" and path == "/chalk-grain.png":
                return self.respond(200, (ROOT / "public" / "chalk-grain.png").read_bytes(), "image/png")
            if self.command == "GET" and path in ("/electronic-countdown.wav", "/priority-heartbeat.wav"):
                return self.respond(200, (ROOT / "public" / path[1:]).read_bytes(), "audio/wav")
            if self.command == "GET" and path in ("/workspace.js", "/activity-chat.js", "/share-code.js", "/classroom-motion.js", "/classroom-drafts.js", "/confirm-delete.js"):
                return self.respond(200, (ROOT / "public" / path[1:]).read_bytes(), "text/javascript; charset=utf-8")
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
            if accounts and self.command == 'POST' and path.startswith('/api/account/'):
                return self.respond(200, accounts.dispatch(token, path.removeprefix('/api/account/'), data))
            if portal or accounts:
                if not accounts:
                    raise QuizError(503, "請先設定 Firebase 帳號登入。")
                if path in ('/api/teacher/login', '/api/join'):
                    raise QuizError(403, "請從課程首頁使用 Google 帳號登入。")
                with service.lock:
                    scope = accounts.scope(token)
                    target = re.fullmatch(r'/api/activities/([a-f0-9]{24})(?:/([a-z-]+))?', path)
                    if target:
                        accounts.access(scope, target[1])
                    if scope['kind'] == 'assistant' and path != '/api/logout':
                        if not target or not ((self.command == 'GET' and target[2] is None) or
                                (self.command == 'POST' and target[2] in ('review','review-batch','review-undo','clusters'))):
                            raise QuizError(403, "助教僅能查看本課程紀錄與批改。")
            if self.command == "POST" and path == "/api/teacher/login":
                return self.respond(200, service.login(data.get("password"), self.client_address[0]))
            if self.command == "POST" and path == "/api/join":
                return self.respond(200, service.join(data.get("code"), data.get("group")))
            if self.command == "POST" and path == "/api/logout":
                if token and not sheets.server_managed:
                    try:
                        sheets.google.disconnect(service.teacher_key(token))
                    except QuizError:
                        pass
                return self.respond(200, service.logout(token))
            if path.startswith("/api/google/"):
                owner = service.teacher_key(token)
                if self.command == "GET" and path == "/api/google/status":
                    return self.respond(200, sheets.google.status(owner))
                if sheets.server_managed:
                    raise QuizError(403, "此網站由伺服器管理學習單授權。")
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
            match = re.fullmatch(r"/api/activities/([a-f0-9]{24})(?:/(start|end|delete|answers|export|sheet-sync|csv|settings|round|review|review-batch|review-undo|clusters|reference|report|bundle|question-settings|chat))?", path)
            if match:
                aid, action = match.groups()
                if action == "chat":
                    if self.command == "GET":
                        after = parse_qs(urlsplit(self.path).query).get("after", ["0"])[0]
                        return self.respond(200, service.chat_messages(token, aid, after))
                    if self.command == "POST":
                        return self.respond(200, service.post_chat(token, aid, data.get("body"), data.get("request_id")))
                if self.command == 'POST' and action == 'delete':
                    return self.respond(200, service.delete_activity(token, aid, data.get('confirmed')))
                if self.command == 'POST' and action == 'question-settings':
                    return self.respond(200, service.question_settings(token, aid, data.get('unit'), data.get('betting_enabled'), data.get('questions')))
                if self.command == "POST" and action == "bundle":
                    return self.respond(200, service.submit_unit(token, aid, data.get("unit"), data.get("answers"), data.get("stake", 0)))
                if self.command == "POST" and action == "reference":
                    return self.managed(service.reference(token, aid, data.get("question"), data.get("answer"), data.get("override", False)), token, aid)
                if self.command == "GET" and action == "report":
                    return self.respond(200, service.report_csv(token, aid), "text/csv; charset=utf-8", "group-report.csv")
                if self.command == "POST" and action == "clusters":
                    return self.respond(200, service.clusters(token, aid, data.get("question")))
                if self.command == "POST" and action == "review":
                    return self.managed(service.review(token, aid, data.get("answer_id"), data.get("verdict"), data.get("revision")), token, aid)
                if self.command == "POST" and action == "review-batch":
                    return self.managed(service.review_batch(token, aid, data.get("question"), data.get("selections"), data.get("verdict")), token, aid)
                if self.command == "POST" and action == "review-undo":
                    return self.managed(service.undo_review_batch(token, aid, data.get("batch_id")), token, aid)
                if self.command == "POST" and action == "settings":
                    return self.respond(200, service.configure(token, aid, data.get("mode"), data.get("fairness", False),
                                                               data.get("duration_seconds", 0), data.get("priority_source")))
                if self.command == "POST" and action == "round":
                    return self.managed(service.round_action(token, aid, data.get("action")), token, aid)
                if self.command == "GET" and action == "csv":
                    return self.respond(200, service.activity_csv(token, aid), "text/csv; charset=utf-8", "classroom-results.csv")
                if self.command == "GET" and action is None:
                    state = service.snapshot(token, aid)
                    if state['role'] == 'teacher': auto_sync.watch(token, aid)
                    return self.respond(200, state)
                if self.command == "POST" and action in ("start", "end"):
                    return self.managed(service.transition(token, aid, "active" if action == "start" else "results"), token, aid)
                if self.command == "POST" and action == "answers":
                    return self.respond(200, service.submit(token, aid, data.get("question"), data.get("answer"), data.get("stake", 0)))
                if self.command == "POST" and action == "export":
                    return self.respond(200, sheets.export(token, aid))
                if self.command == "POST" and action == "sheet-sync":
                    auto_sync.watch(token, aid, retry=True)
                    return self.respond(200, {"message":"已排入同步，請查看學習單同步狀態。"})
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
        # A classroom burst can have dozens of clients connecting at once.
        request_queue_size = 128
        def service_actions(self):
            service.tick()
        def server_close(self):
            auto_sync.close()
            super().server_close()
    server = TimedServer(("127.0.0.1", port), Handler)
    auto_sync.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="課堂搶答系統（本機）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--public-origin", help="雲端網站的完整 HTTPS 網域")
    parser.add_argument("--sheets-service-account", type=Path, help="Google Sheets 專用服務帳戶 JSON 路徑")
    parser.add_argument("--legacy", action="store_true", help="以舊版入口開啟尚未綁定 Firebase 的本機資料庫")
    parser.add_argument("--firebase-config", type=Path, default=ROOT / "credentials" / "firebase.json")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "classroom.sqlite3")
    args = parser.parse_args()
    if args.public_origin and (args.legacy or not args.firebase_config.is_file() or not args.sheets_service_account):
        parser.error("雲端模式需要 Firebase 及 Sheets 服務帳戶設定。")
    if args.sheets_service_account and not args.public_origin:
        parser.error("服務帳戶模式需要 --public-origin。")
    password = secrets.token_urlsafe(32)
    if args.legacy:
        password = os.environ.get("QUIZ_TEACHER_PASSWORD") or getpass.getpass("設定本次教師登入密碼（輸入不顯示）: ")
    if not password:
        parser.error("教師密碼不可空白。")
    service = QuizService(args.db, password)
    try:
        if not args.legacy and args.firebase_config.exists():
            from course_accounts import Courses
            from google.oauth2.id_token import verify_firebase_token
            from google.auth.transport.requests import Request
            import cryptography
            config = json.loads(args.firebase_config.read_text(encoding="utf-8-sig"))
            web = {key: config[key] for key in ('apiKey', 'appId', 'authDomain', 'projectId')}
            if not all(isinstance(v,str) and v.strip() for v in web.values()) or not re.fullmatch(r'[a-z0-9-]+[.]firebaseapp[.]com', web['authDomain']):
                raise ValueError("請使用 Firebase Web 應用程式設定中的預設 authDomain。")
            Courses(service, web, config.get('adminUid'), admin_uids=config.get('adminUids', []))
        sheets = None
        if args.sheets_service_account:
            sheets = SheetsWorkflow(service, ServerSheetsConnection(args.sheets_service_account))
        server = make_server(service, args.port, sheets, portal=not args.legacy, public_origin=args.public_origin)
    except (ValueError, KeyError, ImportError) as error:
        service.close()
        parser.error(f"Firebase 設定無法載入。請參閱 docs/firebase.md。{error}")
    except OSError:
        service.close()
        parser.error("連接埠無法使用，請改用 --port 8001，或停止原服務。")
    print(f"課堂搶答系統 http://localhost:{server.server_port} （Ctrl+C 停止）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
