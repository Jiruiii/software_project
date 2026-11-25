"""Google Sheets REST and desktop OAuth. Credentials never reach browser JSON."""
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from quiz_service import QuizError
from guided_notes import (PROTECTED_TEMPLATES, from_google, from_xlsx, parse_grid,
                          prepare_export, fingerprint, spreadsheet_id, check_legacy_group_targets)

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
API = "https://sheets.googleapis.com/v4/spreadsheets/"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def fetch_bytes(url, body=None, headers=None):
    try:
        with urlopen(Request(url, data=body, headers=headers or {}), timeout=12) as response:
            data = response.read(12_000_001)
            if len(data) > 12_000_000:
                raise QuizError(413, "Google 回應過大，請使用較小的課堂學習單。")
            return data
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise QuizError(403, "Google 權限不足或授權失效。請確認 Sheets API 已啟用、試算表分享對象及編輯權限。") from None
        if exc.code in (400, 404):
            raise QuizError(400, "Google 無法處理此請求。請檢查連結、工作表與 OAuth 設定。") from None
        if exc.code == 429:
            raise QuizError(429, "Google 使用量暫時達上限，請稍後再試。") from None
        raise QuizError(502, "Google 暫時無法回應；請稍後重試，未確認成功的寫入不會標示完成。") from None
    except (URLError, TimeoutError, OSError):
        raise QuizError(502, "無法連線 Google，請確認網路後重試。若剛執行寫回，請先檢查原表。") from None


class SheetsAPI:
    def request(self, owner, sid, body=None, resource_key=None):
        endpoint = API + sid
        if body is None:
            fields = "spreadsheetId,sheets(properties(sheetId,title,sheetType),merges,data(startRow,startColumn,rowData(values(userEnteredValue))))"
            endpoint += "?" + urlencode({"fields": fields})
        else:
            endpoint += ":batchUpdate"
        headers = {"Authorization": "Bearer " + self.access(owner), "Content-Type": "application/json"}
        if resource_key:
            headers["X-Goog-Drive-Resource-Keys"] = f"{sid}/{resource_key}"
        try:
            return json.loads(self.transport(endpoint, None if body is None else json.dumps(body).encode(), headers))
        except (ValueError, TypeError):
            raise QuizError(502, "Google 回應不是有效的工作表資料。") from None


class ServerSheetsConnection(SheetsAPI):
    server_managed = True

    def __init__(self, config_path):
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.service_account import Credentials

        try:
            self.credentials = Credentials.from_service_account_file(
                config_path, scopes=[SCOPE, "https://www.googleapis.com/auth/drive.metadata.readonly"])
        except (OSError, ValueError) as exc:
            raise ValueError("無法載入 Google Sheets 服務帳戶設定。") from exc
        self.refresh_request = GoogleRequest()
        self.transport = fetch_bytes
        self.lock = threading.Lock()

    def status(self, owner):
        return {"server_managed": True, "configured": True, "connected": True,
                "email": self.credentials.service_account_email}

    def access(self, owner):
        from google.auth.exceptions import GoogleAuthError

        with self.lock:
            if not self.credentials.valid:
                try:
                    self.credentials.refresh(self.refresh_request)
                except GoogleAuthError:
                    raise QuizError(502, "伺服器無法取得 Sheets 授權，請通知管理員檢查服務帳戶。") from None
            return self.credentials.token

    def require_link_editor(self, course, sid, resource_key):
        params = {"supportsAllDrives": "true", "fields": "nextPageToken,permissions(type,role)"}
        headers = {"Authorization": "Bearer " + self.access(course)}
        if resource_key:
            headers["X-Goog-Drive-Resource-Keys"] = f"{sid}/{resource_key}"
        while True:
            url = f"https://www.googleapis.com/drive/v3/files/{sid}/permissions?" + urlencode(params)
            try:
                page = json.loads(self.transport(url, None, headers))
            except QuizError as exc:
                if exc.status in (400, 403):
                    raise QuizError(403, "無法查驗共用權限。請確認 Google Drive API 已啟用，並將副本設為「知道連結的任何人：編輯者」。") from None
                raise
            if any(p.get("type") == "anyone" and p.get("role") == "writer" for p in page["permissions"]):
                return
            if not page.get("nextPageToken"):
                raise QuizError(403, "請將副本的「一般存取權」設為「知道連結的任何人」，角色選「編輯者」，再重試。")
            params["pageToken"] = page["nextPageToken"]

    def read_source(self, course, source):
        sid = source["spreadsheet_id"]
        if sid in PROTECTED_TEMPLATES:
            return from_xlsx(self.transport(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"))
        resource_key = source.get("resource_key")
        options = {"resource_key": resource_key} if resource_key else {}
        grids = from_google(self.request(course, sid, **options))
        marker = next((g for g in grids if g.title == "課程設定"), None)
        mode = source.get("sharing_mode", "marked")
        if mode == "auto":
            mode = "marked" if marker else "link"
        if marker and marker.cells.get((0, 0)) != course:
            raise QuizError(403, "這份學習單的課程標記與目前課程不符。")
        if mode == "link":
            self.require_link_editor(course, sid, resource_key)
        elif not marker:
            raise QuizError(403, "請確認副本已分享給服務帳戶，並在「課程設定」分頁 A1 填入本課程代碼（純文字）。")
        source["sharing_mode"] = mode
        return [g for g in grids if g.title != "課程設定"]


class GoogleConnection(SheetsAPI):
    def __init__(self, config_path=None, transport=fetch_bytes):
        self.config_path = Path(config_path or os.environ.get("GOOGLE_OAUTH_CLIENT_FILE") or Path(__file__).parent / "credentials" / "google-oauth-client.json")
        self.transport = transport
        self.lock = threading.RLock()
        self.pending = {}
        self.grants = {}

    def config(self):
        try:
            client = json.loads(self.config_path.read_text(encoding="utf-8"))["installed"]
            if not isinstance(client.get("client_id"), str) or not client["client_id"].endswith(".apps.googleusercontent.com"):
                raise ValueError()
            return {k: client[k] for k in ("client_id", "client_secret") if k in client}
        except (OSError, KeyError, ValueError, TypeError):
            raise QuizError(409, "尚未設定 Google OAuth。請依 Google 設定說明，把電腦版用戶端 JSON 放入 credentials/google-oauth-client.json，再重新連線。") from None

    def status(self, owner):
        try:
            self.config(); configured = True
        except QuizError:
            configured = False
        with self.lock:
            grant = self.grants.get(owner)
            connected = bool(grant and (grant.get("refresh_token") or grant.get("expires_at", 0) > time.time()))
        return {"configured": configured, "connected": connected}

    def start(self, owner, origin):
        client = self.config()
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        redirect = origin + "/oauth/callback"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        with self.lock:
            self.pending = {s:p for s,p in self.pending.items() if p["expires"] > time.time() and p["owner"] != owner}
            self.pending[state] = {"owner": owner, "verifier": verifier, "redirect": redirect, "expires": time.time()+600}
        return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code",
            "scope": SCOPE, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            "access_type": "offline", "prompt": "consent"})}

    def finish(self, state, code, error, owner_active):
        with self.lock:
            pending = self.pending.pop(state, None)
        if not pending or pending["expires"] < time.time() or not owner_active(pending["owner"]):
            raise QuizError(400, "授權連結已失效，請回教師頁重新按連線。")
        if error or not code:
            raise QuizError(400, "Google 授權未完成；可回教師頁重新連線。")
        body = {**self.config(), "code": code, "code_verifier": pending["verifier"],
                "redirect_uri": pending["redirect"], "grant_type": "authorization_code"}
        payload = self._token_request(body)
        if not owner_active(pending["owner"]):
            raise QuizError(401, "教師登入已失效，請重新連線。")
        with self.lock:
            self.grants[pending["owner"]] = payload

    def _token_request(self, body):
        try:
            payload = json.loads(self.transport(TOKEN_URL, urlencode(body).encode(), {"Content-Type":"application/x-www-form-urlencoded"}))
            if not payload.get("access_token") or (payload.get("scope") and SCOPE not in payload["scope"].split()):
                raise ValueError()
            return {"access_token":payload["access_token"], "refresh_token":payload.get("refresh_token"),
                    "expires_at":time.time()+float(payload.get("expires_in",3600))-30}
        except (ValueError, TypeError, KeyError):
            raise QuizError(502, "Google 授權回應無效或缺少 Sheets 權限，請重新授權。") from None

    def disconnect(self, owner):
        with self.lock:
            self.grants.pop(owner, None)
            self.pending = {s:p for s,p in self.pending.items() if p["owner"] != owner}
        return {"ok":True}

    def access(self, owner):
        with self.lock:
            grant = self.grants.get(owner)
            if not grant:
                raise QuizError(409, "請先在教師頁連線 Google，才可讀取私人表或寫回答案。")
            if grant["expires_at"] <= time.time():
                refresh = grant.get("refresh_token")
                if not refresh:
                    self.grants.pop(owner, None)
                    raise QuizError(409, "Google 授權已到期，請重新連線。")
                try:
                    grant = self._token_request({**self.config(), "grant_type":"refresh_token", "refresh_token":refresh})
                    grant["refresh_token"] = grant.get("refresh_token") or refresh
                    self.grants[owner] = grant
                except QuizError:
                    self.grants.pop(owner, None)
                    raise
            return grant["access_token"]

    def read(self, owner, sid, public=False):
        if not public and self.status(owner)["connected"]:
            return from_google(self.request(owner, sid))
        return from_xlsx(self.transport(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"))


class SheetsWorkflow:
    def __init__(self, service, connection=None):
        self.service = service
        self.google = connection or GoogleConnection()
        self.server_managed = getattr(self.google, "server_managed", False)
        self.previews = {}
        self.preview_lock = threading.Lock()

    def sheet_identity(self, token, owner, aid=None):
        if not self.server_managed:
            return owner
        with self.service.lock:
            scope = self.service.courses.scope(token)
            if scope["kind"] != "owner":
                raise QuizError(403, "只有授課老師可以匯入及寫回學習單。")
            if aid:
                self.service.courses.access(scope, aid)
            return scope["course"]

    def preview(self, token, url, title=None):
        owner = self.service.teacher_key(token)
        sid = spreadsheet_id(url)
        source = {"spreadsheet_id": sid}
        if self.server_managed:
            course = self.sheet_identity(token, owner)
            if sid not in PROTECTED_TEMPLATES:
                self.service.check_sheet_course(sid, course)
            source["sharing_mode"] = "auto"
            keys = parse_qs(urlsplit(url.strip()).query).get("resourcekey", [])
            if keys:
                if len(keys) != 1 or not re.fullmatch(r"[a-zA-Z0-9_-]{1,256}", keys[0]):
                    raise QuizError(400, "共用網址的資源金鑰格式有誤，請重新複製連結。")
                source["resource_key"] = keys[0]
            grids = self.google.read_source(course, source)
        else:
            grids = self.google.read(owner, sid)
        if title is None and len(grids) > 1:
            return {"worksheets":[g.title for g in grids], "needs_selection":True}
        chosen = [g for g in grids if title is None or g.title == title]
        if len(chosen) != 1:
            raise QuizError(400, "請選擇唯一的工作表。")
        source.update(parse_grid(chosen[0]))
        key = secrets.token_urlsafe(24)
        with self.preview_lock:
            self.previews = {k:v for k,v in self.previews.items() if v["expires"] > time.time()}
            self.previews[key] = {"owner":owner, "source":source, "expires":time.time()+600}
        return {"preview_id":key, "sheet_title":source["sheet_title"], "count":len(source["targets"]),
                "targets":[{k:t[k] for k in ("question","unit","cell")} for t in source["targets"]],
                "official_template":sid in PROTECTED_TEMPLATES}

    def import_activity(self, token, key, title):
        owner = self.service.teacher_key(token)
        with self.preview_lock:
            preview = self.previews.get(key) if isinstance(key,str) else None
            if not preview or preview["owner"] != owner or preview["expires"] < time.time():
                raise QuizError(409, "預覽已失效，請重新讀取學習單。")
        source = preview["source"]
        course = self.sheet_identity(token, owner)
        grids = self.google.read_source(course, source) if self.server_managed else self.google.read(owner, source["spreadsheet_id"])
        matches = [g for g in grids if g.title == source["sheet_title"]]
        if len(matches) != 1:
            raise QuizError(409, "工作表已改動，請重新預覽。")
        fresh = {**source, **parse_grid(matches[0])}
        if fresh["sheet_id"] != source["sheet_id"] or fresh["fingerprint"] != source["fingerprint"] or fresh["targets"] != source["targets"]:
            raise QuizError(409, "預覽後學習單已改動，請重新預覽。")
        # Atomic activity creation + source association under one service transaction.
        result = self.service.create_from_source(token, title, fresh, bind_course=(
            course if self.server_managed and source["spreadsheet_id"] not in PROTECTED_TEMPLATES else None))
        with self.preview_lock:
            self.previews.pop(key, None)
        return result

    def export(self, token, aid):
        owner = self.service.teacher_key(token)
        return self._export(self.sheet_identity(token, owner, aid), aid)

    def _export(self, owner, aid):
        with self.service.sheet_export_lock:
            source, winners = self.service._sheet_export_context(aid)
            sid = source["spreadsheet_id"]
            if sid in PROTECTED_TEMPLATES:
                raise QuizError(403, "官方範本僅供讀取。請先在 Google Sheets 建立自己的副本，再匯入該副本。")
            grids = self.google.read_source(owner, source) if self.server_managed else from_google(self.google.request(owner, sid))
            found = [g for g in grids if g.title == source["sheet_title"]]
            if len(found) != 1:
                raise QuizError(409, "來源工作表已移除或改名，請重新匯入。")
            grid = found[0]
            check_legacy_group_targets(source, grid)
            pending=source.get('pending_export')
            if pending:
                if grid.sheet_id!=pending['sheet_id'] or fingerprint(grid,source['targets'])!=source['fingerprint']:
                    raise QuizError(409,'來源結構已變更，無法恢復上次同步，請檢查學習單。')
                observed={}
                for target in source['targets']:
                    q=target['question']
                    if q not in pending['expected']: continue
                    value=grid.cells.get((target['row'],target['col']),'')
                    if value not in (pending['previous'][q],pending['expected'][q]):
                        raise QuizError(409,f"{target['cell']} 已被修改，無法恢復上次同步，已保留原內容。")
                    observed[q]=value
                self.service._recover_export(aid,observed)
                source,winners=self.service._sheet_export_context(aid)
            requests, expected = prepare_export(source, grid, winners, source.get('_closed_questions'))
            if not requests:
                if not self.service._record_export(aid, expected, grid.sheet_id, source['_closed_questions']):
                    raise QuizError(409, "寫回期間老師判定已改變，請重新寫回最新結果。")
                return {"written":len(expected), "message":f"已核對 {len(expected)} 題答案，學習單無須修改。",
                        "url":f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid={grid.sheet_id}"}
            previous={t['question']:grid.cells.get((t['row'],t['col']),'') for t in source['targets'] if t['question'] in expected}
            self.service._journal_export(aid,expected,previous,grid.sheet_id)
            options = {"resource_key": source["resource_key"]} if source.get("resource_key") else {}
            self.google.request(owner, sid, {"requests":requests}, **options)
            verified = self.google.read_source(owner, source) if self.server_managed else from_google(self.google.request(owner, sid))
            after = [g for g in verified if g.sheet_id == grid.sheet_id]
            if len(after) != 1 or fingerprint(after[0], source["targets"]) != source["fingerprint"]:
                raise QuizError(409, "寫回後來源結構已改變，無法確認結果。請立即檢查原表。")
            for target in source["targets"]:
                q = target["question"]
                if q in expected and after[0].cells.get((target["row"],target["col"]), "") != expected[q]:
                    raise QuizError(502, "寫回後內容核對失敗，請檢查原表；未標記匯出成功。")
            if not self.service._record_export(aid, expected, grid.sheet_id, source['_closed_questions']):
                raise QuizError(409, "寫回期間老師判定已改變，已保留本次寫入紀錄，請重新寫回最新結果。")
            return {"written":len(expected), "message":f"已核對 {len(expected)} 題答案寫回原工作表。",
                    "url":f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid={grid.sheet_id}"}
