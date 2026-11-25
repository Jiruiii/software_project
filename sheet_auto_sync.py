"""Background Google writes; classroom operations never wait for network IO."""
import json
import threading

from quiz_service import QuizError


class SheetsAutoSync:
    def __init__(self, workflow):
        self.flow = workflow
        self.service = workflow.service
        self.lock = threading.RLock()
        self.bindings = {}
        self.stop_event = threading.Event()
        self.thread = None
        if self.flow.server_managed:
            # Mark closures in the same transaction, including timer-driven ones.
            with self.service.lock:
                self.service.db.executescript("""
                    CREATE TRIGGER IF NOT EXISTS sheet_round_closed AFTER UPDATE OF round_open ON activity_options
                    WHEN OLD.round_open=1 AND NEW.round_open=0 BEGIN
                        UPDATE sheet_sources SET exported_at=NULL WHERE activity_id=NEW.activity_id;
                    END;
                    CREATE TRIGGER IF NOT EXISTS sheet_game_ended AFTER UPDATE OF phase ON activities
                    WHEN OLD.phase<>NEW.phase AND NEW.phase='results' BEGIN
                        UPDATE sheet_sources SET exported_at=NULL WHERE activity_id=NEW.id;
                    END;
                """)

    def status(self, aid, state, message):
        with self.service.lock:
            if self.service.db.execute('SELECT 1 FROM sheet_sources WHERE activity_id=?', (aid,)).fetchone():
                self.service.sheet_sync_states[aid] = {'state':state, 'message':message}

    def watch(self, token, aid, retry=False):
        owner = self.service.teacher_key(token)
        if self.flow.server_managed:
            if retry:
                self.flow.sheet_identity(token, owner, aid)
                with self.service.lock, self.service.db:
                    self.service.db.execute("UPDATE sheet_sources SET exported_at=NULL WHERE activity_id=?", (aid,))
                    self.status(aid, "queued", "已排入重試。")
            return
        with self.service.lock:
            if not self.service.db.execute('SELECT 1 FROM sheet_sources WHERE activity_id=?', (aid,)).fetchone():
                return
        connected = self.flow.google.status(owner)['connected']
        with self.lock:
            old = self.bindings.get(aid)
            # A second unconnected teacher must not steal the working grant.
            if old and old['owner'] != owner and self.service.teacher_active(old['owner']) and self.flow.google.status(old['owner'])['connected']:
                if retry: old['signature'] = None
                return
            if not old or old['owner'] != owner:
                old = {'owner':owner, 'token':token, 'signature':None, 'connected':connected}
                self.bindings[aid] = old
            if retry or connected != old['connected']:
                old['signature'] = None
                old['connected'] = connected
            if not connected:
                self.status(aid, 'needs_auth', '請先連線 Google；完成後會自動同步已關閉題目。')
            elif old['signature'] is None:
                self.status(aid, 'queued', '已啟用自動同步，等待關題或核對最新答案。')

    def run_once(self):
        if self.flow.server_managed:
            return self.run_server_jobs()
        with self.lock:
            bindings = list(self.bindings.items())
        for aid, binding in bindings:
            if self.stop_event.is_set(): return
            try:
                with self.service.lock:
                    exists = self.service.db.execute('SELECT 1 FROM sheet_sources WHERE activity_id=?', (aid,)).fetchone()
                if not exists:
                    with self.lock:
                        self.bindings.pop(aid, None)
                    continue
                owner, token = binding['owner'], binding['token']
                if not self.service.teacher_active(owner):
                    self.status(aid, 'needs_auth', '教師登入已失效，請重新登入並連線 Google。')
                    continue
                connected = self.flow.google.status(owner)['connected']
                if not connected:
                    binding['signature'] = None
                    self.status(aid, 'needs_auth', '請先連線 Google；完成後會自動同步已關閉題目。')
                    continue
                with self.service.lock:
                    activity = self.service._activity(aid)
                    if not any(self.service._reviewable(activity, r['id']) for r in self.service.db.execute('SELECT id FROM questions WHERE activity_id=?', (aid,))):
                        self.status(aid, 'idle', '已啟用自動同步，關題後會更新學習單。')
                        continue
                source, winners = self.service.export_context(token, aid)
                signature = json.dumps([source['_closed_questions'], winners], sort_keys=True, ensure_ascii=False)
                with self.lock:
                    if self.bindings.get(aid) is not binding: continue
                    with self.service.lock:
                        queued = self.service.sheet_sync_states.get(aid, {}).get('state') == 'queued'
                    # A quick regrade and reversal may return to the same text
                    # while invalidating the earlier confirmation. Recheck once.
                    if binding['signature'] == signature and not queued: continue
                    binding['signature'] = signature
                self.status(aid, 'syncing', '正在同步已結束題目的學習單答案…')
                result = self.flow.export(token, aid)
                latest, current = self.service.export_context(token, aid)
                if json.dumps([latest['_closed_questions'], current], sort_keys=True, ensure_ascii=False) != signature:
                    self.status(aid, 'queued', '判定已更新，正在排入最新答案。')
                    continue
                self.status(aid, 'synced', result['message'])
            except QuizError as error:
                if '判定已改變' in str(error):
                    binding['signature'] = None
                    self.status(aid, 'queued', '判定已更新，正在排入最新答案。')
                else:
                    self.status(aid, 'error', f'同步未完成：{error} 可修正後按「重試同步」。')
            except Exception:
                self.status(aid, 'error', '同步未完成，請檢查 Google 連線後重試。')

    def run_server_jobs(self):
        with self.service.lock:
            jobs = self.service.db.execute("""
                SELECT s.activity_id, l.course FROM sheet_sources s
                JOIN lessons l ON l.aid=s.activity_id JOIN activities a ON a.id=l.aid
                JOIN activity_options o ON o.activity_id=a.id
                WHERE s.exported_at IS NULL AND (a.phase='results' OR
                    (a.phase='active' AND o.mode='sequential' AND (o.round_index>0 OR o.round_open=0)))
            """).fetchall()
        for aid, course in jobs:
            if self.stop_event.is_set():
                return
            try:
                with self.service.lock:
                    state = self.service.sheet_sync_states.get(aid, {})
                    if state.get("state") == "error":
                        continue
                    self.status(aid, "syncing", "伺服器正在同步已關閉題目。")
                result = self.flow._export(course, aid)
                with self.service.lock:
                    saved = self.service.db.execute("SELECT exported_at FROM sheet_sources WHERE activity_id=?", (aid,)).fetchone()
                    if saved and saved[0] is not None:
                        self.status(aid, "synced", result["message"])
            except QuizError as exc:
                if "判定已改變" in str(exc):
                    self.status(aid, "queued", "判定已更新，正在重新同步。")
                else:
                    self.status(aid, "error", f"同步未完成：{exc} 修正後可按「重試同步」。")
            except Exception:
                self.status(aid, "error", "同步未完成，請檢查服務帳戶與試算表分享設定並重試。")

    def start(self):
        if self.thread is not None: return
        def work():
            while not self.stop_event.wait(.5):
                self.run_once()
        self.thread = threading.Thread(target=work, daemon=True, name='sheet-auto-sync')
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
