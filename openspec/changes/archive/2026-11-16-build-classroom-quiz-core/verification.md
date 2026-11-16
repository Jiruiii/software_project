# Verification Report

變更：build-classroom-quiz-core。最終驗收日期：2026-11-16（Asia/Taipei）。本報告取代同日上午尚有兩項待辦的版本，原紀錄保留於 Git 歷史。範圍為本機 15 項核心功能，不包含公網部署、實體校園網路負載及 E-01～E-11。

## Summary

| 面向 | 結果 |
| --- | --- |
| Completeness | 9/9 任務完成；15 個 ADDED requirements、30 個情境均有實作與證據對應。無 REMOVED／RENAMED requirements。 |
| Correctness | 39 項自動回歸、30 組 HTTP／瀏覽器驗收、三種版面真實 Google 匯入／寫回通過。權限失敗等錯誤分支使用明確標示的模擬傳輸。 |
| Coherence | Python 標準函式庫、單程序 SQLite、伺服器權限與順位、700ms 輪詢、動態定位、PKCE、原表純文字寫回符合設計。新工具沿用正式 HTTP 路由，沒有修改產品行為來通過測試。 |

## Executed checks

- `python -m unittest discover -s tests -v`：39 tests，36.915 秒，OK。含原有 37 項及 2 項快照比對器測試，驗證只允許目標答案值變動，其他值、格式、列高、合併格或工作表識別變動仍會被發現。
- `python tests/run_many_groups.py`：2026-11-16 18:31 起執行通過。30 組 × 6 題 × 3 輪共 540 筆答案；同組不同答案競爭只保存一筆；重送保持紀錄；結束後 30 筆全拒絕。
- 畫面驗收另建立 180 筆答案，實際開老師與 3 組學生共 4 個分頁，其餘組以 HTTP 模擬。核對教師全部 180 格、學生隱私與每題不同贏家；開始同步 569ms、結束同步 573ms、老師顯示延遲 326ms，pageErrors=[]。教師與 390px 學生截圖已視覺檢查。
- HTTP 請求 P95 1537.1ms、最大 2055.4ms，與畫面同步為不同指標；本機結果不代表 30 台實體裝置的效能保證。
- `python tests/run_live_sheets.py`：2026-11-16 18:30:46～18:31:16 真實 Google 驗收通過。使用者在一般瀏覽器完成 OAuth，程式新建私人測試表，經正式 HTTP 路由完成匯入／兩組作答／結束／寫回，未使用 FakeGoogle。
- `node --check public/app.js` 與 `openspec validate build-classroom-quiz-core --strict` 通過。
- 既有 `tests/browser-flow.js` 四分頁驗證包含登入、同組分頁、重新整理、草稿、斷線重連、HTML 純文字與手機寬度，當次開始／結束同步 536／867ms；`tests/browser-sheets.js` 已真實讀取公開官方六題並核對預覽／學生畫面。應用程式未修改，這兩份證據沿用；本輪重跑的是上列多人測試與新增真實 Google 測試。

公開證據位於 `docs/evidence/final-2026-11-16/`，包括 unittest.log、many-groups-report.json、中文摘要、兩張瀏覽器截圖與 live-sheets-report.json。私人表連結僅存於被 Git 排除的 output/live-sheets/test-workbook.txt。

## Live Google verification

| 版面 | 題數 | 獨立預期答案格 | 寫入／保留未作答 |
| --- | --- | --- | --- |
| 官方單題範本副本 | 6 | G5、G7、G9、G11、G13、G15 | 5／1 |
| 副本下移八列、右移三欄 | 6 | J13、J15、J17、J19、J21、J23 | 5／1 |
| 自訂完整佔位符 | 2 | A 題 C19、B 題 P3 | 1／1 |

座標是測試預期，不是主程式常數。三種版面的原試算表／工作表識別不變，`=1+1` 回讀為 stringValue 而非公式；重複寫回後完整快照相同。全無人作答活動 written=0 且原表不變；匯入後真正插入一列，匯出回 409，回讀確認拒絕時未誤寫。

除預期答案值外，比對所有取得的儲存值、userEnteredFormat、備註、文字格式片段、資料驗證、合併格、條件格式、交錯色彩、篩選、列欄屬性及試算表／工作表屬性。每種版面前後雜湊相同；不宣稱驗證未取得的外掛或任意 Sheets 功能。

第一次三種版面寫回均通過，但腳本將標記已被答案取代的表重新匯入，預期題數不成立，整體記為失敗。改為用表頭範本執行後續重複匯入情境，再重新授權完整跑過；未放寬驗證條件。兩次共建立兩份測試表，保留於使用者帳號；未修改既有學習單或本機正式資料。授權 token 僅在記憶體，結束後清除。

## Feature traceability

| 編號 | 實作 | 主要證據 | 狀態 |
| --- | --- | --- | --- |
| F-01 | QuizService.login/_auth；app.py；角色介面 | test_f01_roles_auth_and_logout、HTTP 越權、四分頁登入 | 本機通過 |
| F-02 | QuizService.join | test_f02_normalized_groups_and_isolation、同組分頁 | 本機通過 |
| F-03 | SheetsWorkflow.preview/import_activity；create_from_source | 實際公開表六題、預覽／原子失敗／權限測試 | 公開表與三種私人版面真實匯入通過 |
| F-04 | guided_notes.parse_grid/from_xlsx/from_google | 官方表、列欄移動、替代欄序、標記／重複／模糊、移動版面模擬往返 | 本機、公開表與不同版面真實雲端往返通過 |
| F-05 | QuizService.transition；教師開始 | phase_gates、536ms 實測 | 本機通過 |
| F-06 | transition/submit 共用鎖 | 結束競爭、HTTP late answer、學生欄位關閉 | 本機通過 |
| F-07 | snapshot 教師視圖；renderMonitor | HTTP 全組答案／時間、teacher-active.png | 本機通過 |
| F-08 | snapshot 結果；renderResults | HTTP results、teacher-results.png | 本機通過 |
| F-09 | GoogleConnection；SheetsWorkflow.export；prepare_export | 模擬原 ID、stringValue、欄位遮罩、格式保留、衝突、權限、寫後核對及重送；使用者回報單題實際寫回成功 | 單題手動與三種版面真實寫回／儲存格式核對通過 |
| F-10 | submit 伺服器階段檢查 | API 409、學生開場禁用 | 本機通過 |
| F-11 | answers 唯一約束；submit | first_answer_immutable、同組分頁同步 | 本機通過 |
| F-12 | 結果階段學生視圖 | 兩組看到贏家與無人作答 | 本機通過 |
| F-13 | snapshot/submit 資料過濾 | 他組與全域答案 id 不回傳；Sheets source 不回傳學生 | 本機通過 |
| F-14 | 鎖內伺服器順序／答案 id | 20 組併發、偽造時間無效、分頁勝者一致 | 本機通過 |
| F-15 | public/app.js refresh/poll | click 至 DOM 開始 536ms、結束 867ms | 本機通過 |

額外支援要求「建立可驗證的活動」由 test_validation_and_atomic_create 驗證；「基本紀錄保存」由 test_persistence_and_session_expiration 及瀏覽器重新整理驗證。15 個 requirement 與 15 個 F 編號非一對一，兩者分別核對。

## Coherence and delivery

README 保持啟動／操作／測試用途，補上 `.env.example` 僅為環境變數參考、不自動載入 `.env`，以及可信小組名稱限制。組員／助教可自行建立 Desktop OAuth 用戶端及自己的測試名單，不必依賴作者開通；使用作者設定檔則需另行安排測試帳號。真實憑證不隨公開 repository 發布。

來源：使用者功能清單 DOCX、七頁《期末專題說明(大學部).pdf》、五頁《期末專題說明.pdf》及 tests/fixtures/README.md 的官方範本。主程式沒有第三方執行套件，瀏覽器測試使用 Playwright CLI。使用者先前手動回報寫回成功，與本輪獨立 Google API 核對分開記載。

初次 Git 上傳是將既有成果分成七個當時日期的提交，未回填開發時間或偽造 PR。本輪補齊驗收與文件，不將事後整理宣稱為開發前紀錄。

## CRITICAL

無。工作 3.4 真實雲端不同版面往返與工作 4.1 最終核對已完成；9/9 任務通過。

## WARNING

1. Google 前置檢查與寫入不是跨請求交易；他人在兩者之間移動列欄仍有競爭風險。保留「寫回期間不要編輯原表」的操作限制，不宣稱已完全排除。
2. 公開 XLSX 無 Google sheetId，首次公開匯入依來源 ID、名稱與結構指紋定位，首次授權寫回保存 sheetId。需嚴格工作表身分核對時，先連線 Google 再匯入；本輪私人實測採此流程。

可信小組名稱、loopback 單程序與公網／實體裝置效能屬已定義的範圍限制，不以本輪驗收宣稱部署完成。

## Final assessment

任務完整性、規格實作與情境對照、設計及程式一致性均已檢查；0 項 critical、2 項已記載限制、0 項額外建議。可在保留上述限制下同步規格並歸檔本機核心變更。公網部署另行規劃。

## Archive

2026-11-16 已將 classroom-access、guided-notes、quiz-session 同步至 openspec/specs，逐字核對 Purpose 與全部需求／情境，三份規格通過嚴格驗證。本變更移至 openspec/changes/archive/2026-11-16-build-classroom-quiz-core；歸檔後 active changes 為空，`openspec validate --all --strict` 通過。
