# Design

## Context

首批十二項核心已實作與驗收。使用者指出的另一份《期末專題說明.pdf》提供單題及題組範本；已唯讀取得並解析。使用者已確認只做 15 項核心，且先完成 OAuth 程式再設定其 Google Cloud 用戶端；真實授權驗收仍保持未完成。

## Goals / Non-Goals

**Goals:** 本機單程序、多分頁可操作；伺服器控制階段與收件順序；資料保存、真實權限檢查；每個 F 編號有測試或明確待辦。

**Non-Goals:** 本次不部署公網、不實作 Spec Kit、不自動判分、不啟用未決議額外功能，不捏造 commit、PR 與影片。使用者後續指定 GitHub 儲存庫，首次上傳將現有成果按責任分批提交，保留實際時間並明示為實作後整理。核心程式不依賴 Google 即可獨立測試，但手動題號不能算完成 Google 匯入。

## Decisions

### 執行環境與資料

採 Python 3.11+ 標準函式庫（現有 3.13.5 可用）：`ThreadingHTTPServer`、`sqlite3`、`unittest`，前端採原生 HTML/CSS/JavaScript。相較引入前後端框架，本機課堂範圍可減少安裝成本；HTTP server 僅綁定 loopback，不宣稱適合公網服務。SQLite 以單一服務鎖序列化資料異動，答案寫入交易與活動結束共用鎖，避免結束後仍收件或同題產生多位成功者。

資料模型：activities(id, code, title, phase, created_at, started_at, ended_at)、questions(activity_id, id, ordinal)、groups(id, activity_id, name, normalized_name)、sessions(token_hash, role, activity_id, group_id, expires_at)、answers(id, activity_id, question_id, group_id, text, received_at, elapsed_ms)。每組每題有唯一約束；答案 id 為伺服器序號，於互斥接收點產生伺服器時間，順位依序號。日期保存為 UTC、前端顯示本地時間。採 SQLite 保存而非記憶體，以滿足基本紀錄及重新啟動。

### 權限與資料輸出

教師啟動時輸入密碼，或用環境變數 `QUIZ_TEACHER_PASSWORD`，不提供固定預設密碼。登入後簽發不可猜測 token，資料庫只存其雜湊；分頁以 sessionStorage 保存，支援同瀏覽器多角色演示。學生以活動代碼及小組名稱加入，這是信任課堂模式，沒有學校帳號認證，相同小組名稱可以加入同組；需在 README 明示。Token 24 小時到期。教師只能管理經教師登入後取得的教師權限；所有學生 API 校驗活動歸屬。

學生在結束前的回應只有題號、階段、本組及本組答案。教師回應另含全組別與答案；學生不能從原始 JSON 或答案送出回應推知他組先後。結果階段加上每題成功答案。答案文字用 DOM textContent 呈現，避免 HTML 注入。只接受 JSON 寫入與 loopback Host，不允許跨來源 API；請求本文限 64 KiB。

### 活動與互動

教師首頁列出過去活動並可新增；每行一個題號（1～100 題，題號最多 40 字元），活動名最多 100 字元。學生活動代碼為六位大寫英數字，小組名最多 40 字元。同組同題採首筆不可變，重送相同答案回原結果、不同答案回 409。只允許準備中 → 作答中 → 結果，對同一目標階段的重送冪等；新一輪需建立新活動。

前端每 700 毫秒輪詢一次且不重疊請求，操作後立即刷新；2 秒同步門檻以本機正常網路驗證。分頁有獨立 token，登出撤銷 token；狀態更新保留未送出草稿與焦點，不重建正在輸入的欄位。連線失敗停用送出並顯示提示，重新連線後恢復。

API：POST /api/teacher/login、POST /api/join、POST /api/logout；GET /api/activities（教師）；POST /api/activities（教師）；GET /api/activities/{id}；POST /api/activities/{id}/start、/end（教師）；POST /api/activities/{id}/answers（學生）。錯誤以結構化 JSON 與 400/401/403/404/409 回應。

### Google Sheets 整合

官方單題表有六題，表頭為「題號／題目／作答」，答案區為橫向合併儲存格。掃描表頭定位欄位，再從題號與題目內容定位列，以合併範圍左上角作為答案寫入點；座標僅是解析結果而非程式常數。若題號跨列合併或同題有多列，視為未啟用的題組功能並拒絕。替代版面可在答案格放 `{{Q:題號}}`，同格僅一個完整標記，重複或部分標記拒絕。這符合五頁專題說明允許佔位符的規定。

公開來源以 Google Sheets 官方 XLSX 匯出唯讀取得，解析 workbook、sharedStrings、worksheet 與 merges；不產生本機試算表交付。私人來源以授權的 Sheets API 取得相同正規化格線。教師先預覽工作表、題號與定位，確認後才建立活動；多工作表必須選擇。保留來源試算表 ID、工作表名稱／可取得的 sheetId、題號至格線座標對應、非答案內容及合併結構雜湊、原答案值。學生回應不提供來源連結或題目敘述。

使用者選擇 Google OAuth Desktop 設定檔，路徑預設 `credentials/google-oauth-client.json` 或環境變數 `GOOGLE_OAUTH_CLIENT_FILE`。採 PKCE S256、單次 state、10 分鐘有效與本機 callback。Google token 僅存在伺服器記憶體，依教師 session 雜湊隔離，重新登入／重啟須重新連線；不傳回前端、不寫入資料庫。設定檔缺失時公開匯入仍可用，登入按鈕說明缺少設定；不偽造 OAuth 成功。

寫回僅允許教師、結果階段、有來源對應的活動。先取得該工作表最新格線，核對 sheetId／名稱、非答案格內容、合併結構以及目標值未被外部修改；無人作答不寫入。使用 Sheets batchUpdate 的 updateCells，僅設定 userEnteredValue.stringValue，避免公式執行及格式破壞。完成後重新讀取核對每個目標值才呈現成功。原官方兩個範本 ID 設為唯讀保護，要求使用者先複製自己的版本。重複匯出同結果可冪等處理。

外部請求與活動狀態鎖分離，Google 慢回應不阻塞學生輪詢。匯出以獨立鎖避免本機並行重送；Google API 無跨前置讀取及寫入的比較交換，因此匯出期間需避免其他人移動欄列，程式進行前後核對但不承諾能排除外部同時編輯競爭。變更偵測採保守策略，無關文字變動也要求重新匯入。

新增教師 API：GET /api/google/status，POST /api/google/connect、/disconnect，GET /oauth/callback，POST /api/sheets/preview、/import，POST /api/activities/{id}/export。預覽在教師記憶體 session 中有效 10 分鐘，匯入時重新讀取避免使用過期映射。

參考：[OAuth Desktop](https://developers.google.com/identity/protocols/oauth2/native-app)、[Sheets get](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get)、[Sheets batchUpdate](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate)。

## Risks / Trade-offs

- 小組名稱可被其他學生選用 → 本機可信課堂演示明示限制，正式環境需另立認證規格。
- 輪詢有短暫延遲 → 顯示連線狀態且以伺服器階段拒絕過期送出，不採用畫面時間判定。
- 單程序鎖限制吞吐量 → 符合本機課堂範圍，多實例部署不在本次承諾。
- 選做項目已確定不納入本輪 → 不改動最快者成功規則，題組表明確提示 E-09 尚未啟用。

## Migration Plan

首次啟動建立 data/classroom.sqlite3，未提供密碼時互動提示。停止程序即可停止服務；本次沒有既有資料遷移。回退程式前先備份資料庫。憑證、data/、暫存輸出列入 .gitignore，原始使用者文件保持不變。
