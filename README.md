# 課堂搶答系統

本機教師／學生多分頁搶答，使用 OpenSpec 追蹤功能清單 F-01～F-15。

## Git 提交與協作

儲存庫：https://github.com/Jiruiii/software_project 。本次為既有本機成果首次建立 Git 紀錄，依環境、規格、核心服務、Google 整合、介面、多人測試及文件分批提交；這些提交是實作完成後的整理，時間為實際提交時間，不代表先前每一步開發當時已有 Git 紀錄。規格中的進度勾選是首次入庫時的真實狀態，不倒填成早期進度。

目前提供的兩份期末專題說明與 OpenSpec 小投票器教學，未見每功能必須各自一個 commit 的硬性條文。五頁專題說明第 2～3 頁要求 GitHub 保存程式與文件，並把 branch／pull request 協作列為加分項；七頁大學部說明第 4 頁禁止偽造 Git／測試／協作紀錄。OpenSpec 的一個 change 可包含多個合理大小的 commit。

後續修改建議每次聚焦一個可驗證的變更，連同必要規格、程式、測試與文件一起提交；組員可開功能分支、提出 pull request 並互相審查。首次上傳不製造假分工、假 PR 或補造歷史時間。尚待雲端不同版面驗收的工作維持未勾選，不為上傳而歸檔。

憑證、權杖、正式資料庫、暫存測試輸出與使用者原始規劃附件不納入版本控制；`.env.example` 只有設定欄位，沒有真實密碼。使用者需自行放入自己的 OAuth JSON，不能從 GitHub 取得真實憑證。

## 執行環境

Python 3.11 以上，應用程式不需安裝第三方套件。開發檢查使用 OpenSpec 2.0.0。

## 身分與規則

- 教師使用啟動時設定的密碼登入。沒有固定預設密碼，不需把密碼貼進聊天或儲存庫。
- 學生使用六位活動代碼與小組名稱加入；同活動、同名稱（忽略英文大小寫及前後空白）視為同組。這是可信課堂演示，不是學校帳號身分驗證。
- 各分頁獨立保存登入身分，可以同瀏覽器模擬老師與多組學生；身分 24 小時到期。
- 每組每題僅第一筆答案有效，同答案重送不改順位，不同答案重送拒絕。空白與超過 2000 字元的答案拒絕。
- 搶答先後依伺服器接收點序列化的順序，不採用學生時間；時間相同仍由伺服器序號決勝。此階段不判斷答案是否正確。
- 只能「準備中 → 作答中 → 結果」，重玩需新建活動。學生在結果公開前只能取得自己組別的答案。
- 活動與答案存於 data/classroom.sqlite3，重啟保留。請勿同時以兩個伺服器程序共用同一資料庫。

## 測試

在此資料夾執行：

```powershell
python -m unittest discover -s tests -v
openspec validate build-classroom-quiz-core --strict
```

## 啟動與演示

也可以雙擊 `start-classroom.cmd`，再依提示設定教師密碼。

```powershell
cd D:\software_project
python app.py
```

依提示設定至少 8 字元的教師密碼，輸入時不顯示。打開 http://127.0.0.1:8000 。若連接埠已使用，執行 `python app.py --port 8001`。也可先於自己的終端機設定 `QUIZ_TEACHER_PASSWORD` 環境變數，伺服器不會自動讀取 .env。

1. 第一個分頁選教師，輸入剛設定的密碼。
2. 輸入活動名稱及逐行題號，例如 1、2、3，建立活動。
3. 另開兩個分頁，選學生，輸入畫面活動代碼及不同小組名稱。
4. 教師按開始搶答，兩組分別作答；老師即時看到各組答案，學生只能看到本組。
5. 教師按結束搶答，所有分頁自動顯示每題成功組別與答案。
6. 教師回到活動清單可查看既有活動。停止使用時在終端機按 Ctrl+C。

每 700 毫秒更新狀態，正常本機網路的目標為 2 秒內同步。斷線會停用送出並提示，恢復後重新取得階段。此服務僅供本機多分頁演示，綁定 127.0.0.1。

## API

所有寫入使用 JSON，登入後以 `Authorization: Bearer <token>` 傳入權限。不得把 token 記錄到文件或版本控制。學生回應在結果階段前不含他組資訊，也不含可推知全域送出數的答案流水號。

| 方法及路徑 | 用途 |
| --- | --- |
| POST /api/teacher/login | password 換取教師身分 |
| POST /api/join | code、group 加入活動 |
| POST /api/logout | 撤銷目前身分 |
| GET /api/activities | 教師活動清單 |
| POST /api/activities | 教師建立 title、questions 陣列 |
| GET /api/activities/{id} | 依權限取得階段、題號與答案 |
| POST /api/activities/{id}/start | 教師開始 |
| POST /api/activities/{id}/end | 教師結束 |
| POST /api/activities/{id}/answers | 學生送出 question、answer |
| GET /api/google/status | 教師檢查設定／連線狀態，不回傳 Google token |
| POST /api/google/connect、/disconnect | 建立授權連結／清除目前教師 Google 連線 |
| GET /oauth/callback | Google 回呼，驗證單次 state 與有效教師身分 |
| POST /api/sheets/preview | 教師提供 url、選填 worksheet，預覽題號與答案格 |
| POST /api/sheets/import | preview_id、title，重新核對來源後原子建立活動 |
| POST /api/activities/{id}/export | 教師在結果階段寫回原學習單並核對 |

錯誤以 `{ "error": "說明" }` 回傳；400 為內容無效，401 為未登入或失效，403 為權限不足，404 為不存在，409 為階段／重送衝突，413 為內容過大，415 為非 JSON，429 為密碼嘗試過於頻繁。

## 目前範圍

15 項核心功能皆已有程式。前 12 項課堂功能已通過服務、HTTP 與四分頁瀏覽器驗收；F-03／F-04 已實際讀取官方公開單題表、匯入六題，並用不同版面測試動態定位。F-09 的 OAuth 與原表寫回已通過模擬傳輸測試；2026-11-16 使用者完成設定與操作後，回報「寫回成功」。這是使用者回報的單題實際驗收，尚未補齊不同版面的雲端往返與完整格式核對。E-01～E-11 依使用者決議不納入。

規格與逐項工作清單位於 `openspec/changes/build-classroom-quiz-core/`；驗收對照見同目錄 `verification.md`。目前 7/9 項工作完成，保留真實 Google 驗收及最終整體核對，未 sync／archive。OpenSpec 的規劃文件完成狀態不等於實作全部驗收完成。

## Google Sheets 操作

首次設定請開啟教師頁的「首次設定說明」，或閱讀 `public/google-setup.html`。建立 Google Cloud 專案、啟用 Sheets API、設定自己的測試使用者、建立 **電腦版應用程式** OAuth 用戶端，將 JSON 放在 `credentials/google-oauth-client.json`。也可透過 `GOOGLE_OAUTH_CLIENT_FILE` 指定自己的本機檔案。參考 [Google 官方設定文件](https://developers.google.com/workspace/sheets/api/quickstart/python)及 [Desktop OAuth 文件](https://developers.google.com/identity/protocols/oauth2/native-app)。

1. [複製官方單題範本](https://docs.google.com/spreadsheets/d/12uh5xhIx2wXFMy42KU8lN7rLFQ8GDugt9zfAFEvu-1E/copy)，保留自己的副本網址。官方原範本只能試讀，程式禁止寫入。
2. 教師頁按「連線 Google」，點開授權連結，在 Chrome／Edge 完成授權後回原分頁。
3. 貼上副本連結並預覽；多工作表時選擇其中一張，核對題號、題數與答案格後建立活動。預覽有效 10 分鐘。
4. 學生加入、教師開始、學生作答、教師結束，再按「寫回成功答案」。畫面只有在重新讀取原表確認內容一致後才標示寫回成功。無人作答的格子保留原值。
5. 在自己的原副本核對答案、題目與格式；再用另一份先移動列欄的副本測試同樣流程。使用者已回報單題寫回成功，不同版面及完整格式核對仍待補齊。

支援「題號／題目／作答（或答案）」表頭與單列答案區，位置可移動；也支援每個答案格完整且唯一的 `{{Q:題號}}`。若同時有題號表頭，必須所有題目與標記一致，避免漏題。原位標記寫回後會被答案取代；自訂純標記學習單再次使用前需恢復標記。題組同時送出屬 E-09，本輪明確拒絕，不能直接使用題組範本。

Google 憑證只從本機讀取，access／refresh token 僅存伺服器記憶體，教師登出或重啟後需重新連線。學生 JSON 不含原表連結或 Google 權杖。不要把憑證、資料庫或權杖加入版本控制。

寫回只更新對應格的純文字值，答案即使以 `=` 開頭也不執行公式。匯入後修改非答案內容、列欄或合併區會要求重新匯入；外部手改答案會停止覆蓋。Google 不提供跨本程式前置檢查與寫入的比較交換，因此寫回期間請勿同時編輯來源。網路失敗可能發生在 Google 已寫入之後；先檢查原表，重送相同結果可再次核對，不建立替代工作表。

### 重跑瀏覽器驗收

此為開發測試選項，不是執行應用程式的必要安裝。先在獨立終端機啟動合成資料測試服務：

```powershell
$env:QUIZ_TEACHER_PASSWORD='classroom-qa-only'
python app.py --port 8765 --db tmp/qa.sqlite3
```

另開終端機執行（需能下載 Playwright CLI，且已有 Chrome）：

```powershell
New-Item -ItemType Directory -Force output/playwright | Out-Null
npx.cmd --yes --package @playwright/cli playwright-cli -s=classroom-qa open http://127.0.0.1:8765
npx.cmd --yes --package @playwright/cli playwright-cli -s=classroom-qa run-code --filename tests/browser-flow.js
npx.cmd --yes --package @playwright/cli playwright-cli -s=classroom-qa run-code --filename tests/browser-sheets.js
npx.cmd --yes --package @playwright/cli playwright-cli -s=classroom-qa close
```

第一個腳本在測試瀏覽器建立老師、兩組學生與一個同組分頁，量測實際點擊至各分頁 DOM 更新時間。第二個腳本需要網路，讀取官方公開表並匯入，檢查手機版面及禁止寫回官方範本；不進行真實 Google 授權或雲端寫入。資料與截圖只存 tmp/、output/，不混入正式活動資料；測試後停止測試伺服器。CLI 為測試工具（Playwright 專案，Apache-2.0 授權）。

### 一鍵測試多組搶答

雙擊 `test-many-groups.cmd`，或在此資料夾執行：

```powershell
python tests/run_many_groups.py
```

會自動建立暫時資料庫及空閒本機連接埠，測試後關閉服務與專用測試瀏覽器，不操作你的 8000 連接埠、正式活動、Google 憑證或試算表。第一次執行瀏覽器檢查需要能下載 Playwright CLI，且電腦已有 Chrome。

- 30 組使用真正 HTTP 請求同步送出，6 題、連續 3 輪，共 540 筆答案；核對完整性、每題唯一贏家、所有組別結果一致與結束前隱私。
- 30 次同組不同答案競爭只能保存一筆；相同答案重送不改時間。老師結束與 30 組送出競爭後，另外 30 筆遲到答案都必須拒絕。
- 另建立 30 組、180 筆答案的畫面驗收，實際開老師及 3 組學生分頁。每題先由不同指定組別送出，再讓其餘 29 組同時送出，核對老師每格答案／時間及各頁面不同贏家，避免結果套錯題。

結果存於 `output/playwright/many-groups-summary.txt`（中文摘要）與 `many-groups-report.json`；截圖為 `many-groups-teacher-active.png`、`many-groups-teacher-results.png`、`many-groups-student-results.png`。報告會記錄失敗，不以重試掩蓋漏單。若只需 HTTP 測試，可加 `--http-only`。這是本機模擬，不能直接代表 30 台手機在實際校園網路下的表現。

GitHub 上可直接查看[已執行的測試證據](docs/evidence/README.md)，包含結果資料及老師／學生畫面；這份快照只含合成測試內容。

## 規格來源與授權

需求來源為使用者提供的功能清單 DOCX 與期末專題 PDF。程式及介面於此專案新建，執行時只使用 Python 標準函式庫與瀏覽器 API，沒有外部字型、圖庫或付費 API。測試資料均為合成資料，不是假造的學生紀錄。OpenSpec 是開發工具（MIT 授權）；Python 標準函式庫依 Python Software Foundation 授權。
