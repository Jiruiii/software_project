# 部署課堂網站到 Azure

使用單一 Ubuntu Server 24.04 LTS x64 VM、Caddy、systemd，以及持久磁碟上的 SQLite。Google 登入繼續使用現有 Firebase 專案。更新程式時，課堂資料與憑證分別留在 `/var/lib/classroom` 與 `/etc/classroom`。

## 建立主機

1. 在 Azure Portal 選使用中的 Azure for Students 訂閱，建立資源群組。依訂閱允許區域、規格可用性及入口網站顯示的運算、持久磁碟與公用 IP 費用確認後再建立 VM。選 Ubuntu Server 24.04 LTS、SSH 公開金鑰、持久化受控 OS 磁碟。請保留 SSH 私鑰在自己的電腦。
2. 使用固定公用 IP。在公用 IP 的「設定」指定 DNS 名稱標籤，複製實際完整網域。網路安全性群組允許 Internet 的 TCP 80、443；管理用的 22 限管理者來源 IP。應用程式的 8000 僅供 VM 本機使用。
3. Firebase Authentication 的「設定 → 已授權網域」加入完整主機名稱。維持 Google 提供者、既有 Firebase Web 設定和管理員 UID。

參考 [Azure 建立 Linux VM](https://learn.microsoft.com/azure/virtual-machines/linux/quick-create-portal) 與 [Firebase Google 登入](https://firebase.google.com/docs/auth/web/google-signin)。

## 準備資料和 Google Sheets

1. 在同一 Google Cloud 專案啟用 Google Sheets API 及 Google Drive API；現有 Sheets 服務帳戶金鑰可繼續使用。Drive API 用來查驗試算表共用權限，Sheets API 用來讀寫原格。詳見 [Google 的服務帳戶設定](https://developers.google.com/workspace/guides/create-credentials) 與 [Drive 權限查詢](https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions/list)。
2. 老師將副本的「一般存取權」設為「知道連結的任何人：編輯者」，從課程貼網址並確認匯入。網站會保存課程與副本的關聯。之前透過私人分享匯入的活動仍依「課程設定」分頁 A1 判斷課程。
3. 安排停寫時段，先停止本機服務。保存 `data/classroom.sqlite3` 的一致備份（如有使用中的 SQLite 日誌，應用 SQLite backup API 建立備份）。核對備份的 `PRAGMA integrity_check` 為 `ok`，並記下課程、學生組別、作答數量。保留原備份，準備另一份供搬移。
4. 在 Windows 專案根目錄製作僅含執行檔案的封裝，避免帶入本機環境與憑證。用 SSH/SCP 傳送程式封裝到 VM 使用者家目錄。另透過 SSH 傳送資料庫備份、現用 Firebase Web JSON、Sheets 服務帳戶 JSON，分別命名 `classroom.sqlite3`、`firebase.json`、`sheets.json`，放入該帳號的私人暫存目錄。

```powershell
tar -czf "$env:TEMP/classroom-app.tar.gz" app.py course_accounts.py google_sheets.py guided_notes.py quiz_extras.py quiz_service.py sheet_auto_sync.py requirements-firebase.txt public deploy
```

## 首次安裝

以下以 SSH 進入新 VM 後操作。設定路徑以 systemd 單元為準。將下方的完整網域換成 Azure 公用 IP 頁面顯示的 DNS 名稱。

```bash
sudo apt update
sudo apt install python3-venv sqlite3 caddy
sudo useradd --system --user-group --home-dir /var/lib/classroom --shell /usr/sbin/nologin classroom
sudo install -d /opt/classroom
sudo tar -xzf ~/classroom-app.tar.gz -C /opt/classroom
sudo python3 -m venv /opt/classroom/.venv
sudo /opt/classroom/.venv/bin/pip install -r /opt/classroom/requirements-firebase.txt
sudo install -d -m 0750 -o root -g classroom /etc/classroom
sudo install -d -m 0700 -o classroom -g classroom /var/lib/classroom
```

切換至上傳三份私人檔案的目錄。只在首次搬移且目標資料庫尚不存在時安裝資料庫。

```bash
sudo install -m 0640 -o root -g classroom firebase.json sheets.json /etc/classroom/
sudo test ! -e /var/lib/classroom/classroom.sqlite3 && sudo install -m 0600 -o classroom -g classroom classroom.sqlite3 /var/lib/classroom/
sudo -u classroom sqlite3 /var/lib/classroom/classroom.sqlite3 'PRAGMA integrity_check;'
sudoedit /etc/classroom/site.env
```

在環境檔放一行 `PUBLIC_ORIGIN=https://你的完整網域`，尾端不加斜線。在 `/etc/caddy/Caddyfile` 以同一個實際主機名稱取代預設站台。

```caddyfile
你的完整網域 {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo install -m 0644 /opt/classroom/deploy/classroom.service /etc/systemd/system/classroom.service
sudo systemctl daemon-reload
sudo systemctl enable --now classroom
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
sudo systemctl status classroom caddy
```

Caddy 需要 DNS 指到這台 VM，並可由外部連入 80、443，才能自動取得及續期憑證。參閱 [Caddy 安裝](https://caddyserver.com/docs/install) 與 [Automatic HTTPS](https://caddyserver.com/docs/automatic-https)。

## 讓 GitHub main 自動更新正式站

在本機照常 pull、修改、commit，再 push 到 GitHub 的 `main`。VM 上的計時器約每分鐘檢查一次，有新提交才準備獨立版本和 Python 環境。切換時 classroom 會短暫重啟，建議課後推送正式版。功能分支合併到 main 時才部署。資料庫沿用 `/var/lib/classroom/classroom.sqlite3`，Firebase 與 Sheets 設定沿用 `/etc/classroom`。

### 首次啟用

1. 先把目前正式站使用的 Azure、Sheets 修正與本次自動部署檔案一起提交並推到 main。在開發機記下已核對的完整提交 ID（`git rev-parse HEAD`）。首次安裝會比對 GitHub 上的 main 和此 ID。
2. 在 Windows 專案根目錄執行 `git archive -o output/classroom-update-bootstrap.tar.gz HEAD deploy`，以既有的 SCP 連線傳送這個安裝包一次。在 VM 執行 `mkdir -p ~/classroom-bootstrap && tar -xzf ~/classroom-update-bootstrap.tar.gz -C ~/classroom-bootstrap && cd ~/classroom-bootstrap/deploy`。安裝包只含部署檔案。
3. 公開庫使用 `https://github.com/Jiruiii/software_project.git`。私人庫先在 VM 執行 `sudo bash install-update.sh --key`，將顯示的公鑰加到 GitHub 專案的 **Settings → Deploy keys → Add deploy key**，維持預設的唯讀權限，並使用 `git@github.com:Jiruiii/software_project.git`。專用私鑰留在 VM。參閱 [GitHub Deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)。
4. 在同一個 VM 目錄執行 `sudo bash install-update.sh 儲存庫網址 完整提交ID`。第一次成功啟動並通過健康檢查後會啟用計時器。用 `cat /var/lib/classroom-deploy/active` 核對正式站版本，並以 `systemctl list-timers classroom-update.timer` 查看下次檢查時間。
5. 下次推送後，核對正式站版本、HTTPS 登入與原課程紀錄。可用 `sudo journalctl -u classroom-update.service -n 40 --no-pager` 查看結果。

### 更新失敗時

建置失敗會保留運行中的程式。新服務未通過健康檢查時會切回上個程式版本，將錯誤提交記錄在 `/var/lib/classroom-deploy/failed`。推送修正版後會部署新提交；若故障原因已排除而要重試同一提交，在 VM 刪除該標記後執行 `sudo systemctl start classroom-update.service`。部署中斷時，下次執行會先依切換紀錄恢復。程式回復沿用當下的資料庫，涉及不相容資料遷移的版本請先安排備份與維護時段。

要暫停後續更新可執行 `sudo systemctl disable --now classroom-update.timer`。上述安裝腳本與 systemd 設定屬於主機配置，日後若變更這些配置需另外安裝；一般前後端程式及 Python 相依套件會隨 main 部署。

## 驗收、更新及還原

- 從不同網路開啟 HTTPS 網站，以原本的管理員、老師、助教和學生登入。核對課程、各組累積分數、作答及批改紀錄與搬移前相符。先用測試副本執行逐題與全題搶答，核對關題、老師答案、改判及還原的原格內容。
- 測試教師登出及服務重啟後的背景寫回；撤下編輯權時應顯示同步錯誤，恢復權限後可重試。跨課程私人副本應無法預覽。資料及外部驗收完成後再提供正式網址。
- 維護時使用 SQLite 的 `.backup` 保存當下資料庫，對備份執行 `PRAGMA integrity_check;`，並保存一份受限的異機備份。更新時只替換程式、更新虛擬環境套件並重新啟動 classroom。
- 需要回復時先停止寫入並備份雲端最新資料。程式可回復前一版本；若需要還原資料庫，請在停機時確認還原點與可能失去的新增紀錄，再還原經驗證的備份。確認只有一個服務在寫同一份試算表。
