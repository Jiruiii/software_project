# Verification Report

變更：build-classroom-quiz-core。驗收日期：2026-11-16（Asia/Taipei）。本報告區分自動化測試、使用者手動回報與尚未核對的情境。使用者已完成 Google 用戶端設定，並於同日回報「寫回成功」；不同版面雲端往返與完整格式核對仍待補齊。

## Summary

| 面向 | 結果 |
| --- | --- |
| Completeness | 7/9 工作完成；15 個 ADDED requirements 均有程式對應。F-01～F-15 全部已實作，Google 單題寫回有使用者成功回報，完整雲端及整體最終驗收仍待補齊。無 REMOVED／RENAMED requirements。 |
| Correctness | 原有 34 項自動測試通過，另新增 3 項多組 HTTP 併發測試通過；四分頁課堂流程及公開官方表實際匯入通過。Google 單題寫回由使用者手動回報成功。Not verified：不同版面的真實雲端往返、原 Sheet ID／完整格式的獨立比對；尚未取得該情境證據。 |
| Coherence | 符合標準函式庫、SQLite、伺服器權限、700ms 輪詢、動態定位、PKCE、原表純文字寫入及前後核對設計。Google 同時外部編輯仍有競爭限制，已明示。 |

## Executed checks

- `python -m unittest discover -s tests -v`：34 tests，OK。含 20 組併發、同組重送、結束競爭、紀錄保存、越權／資料隔離、實際範本解析、多工作表、預覽失效、原子匯入、OAuth PKCE／state／刷新、模擬格式保持與錯誤處理。
- `node --check public/app.js` 與 Python 編譯檢查通過。
- `openspec validate build-classroom-quiz-core --strict`：通過。僅驗證規格格式，不能代替真實 Google 驗收。
- `tests/browser-flow.js`：老師 + 兩組學生 + 同組另一分頁，最新 passed=true、startSyncMs=536、endSyncMs=867、pageErrors=[]。這是本機一次量測，不是所有網路／負載下的效能保證。
- 原量測從自動化命令開始到工具確認結束，曾超出 2 秒；改為瀏覽器中實際 click 事件至各學生 DOM 更新的時間戳，排除測試通訊延遲，仍要求每個分頁在 2 秒內更新。沒有放寬門檻或修改輪詢速度。
- 四分頁亦檢查開始前禁用、同組答案同步、他組隱私、教師紀錄、成功組別、無人作答、HTML 純文字、重新整理保存、草稿保留、390px 手機及斷線重連。
- `tests/browser-sheets.js`：實際從 Google 公開 XLSX 匯出讀取官方單題表，預覽／匯入／學生端均為六題；答案格自動辨識 G5、G7、G9、G11、G13、G15。這些座標是此次範本結果，非程式常數。官方表寫回被拒絕。realGoogleWriteTested=false。
- 不同版面測試：整表下移八列、右移三欄，定位 J13、J15、J17、J19、J21、J23；模擬完整匯入／作答／寫回使用 sheetId=42、J13，沒有寫入舊座標。另測答案欄在題號欄左側及 C19/P3 自訂標記。
- `output/playwright/sheets-preview.png`、`sheets-mobile.png` 已視覺檢查；版面清楚、無橫向溢出。既有 entry、teacher-results、student-mobile 截圖重跑更新。
- 前次測試資料存 `tmp/qa-sheets.sqlite3`，沒有真實學生資料；測試 Google 用戶端與權杖均為合成文字。代理未做真實雲端寫入；後續使用者自行操作並回報單題寫回成功。

## Many-group verification

使用者追加要求以程式驗證多組同時搶答。新增 `tests/test_many_groups.py`、`tests/browser-many-groups.js`、`tests/run_many_groups.py` 與 `test-many-groups.cmd`，沿用工作 4.1 的驗收範圍；未更動應用程式行為。

- 最新完整執行：2026-11-16 13:11（Asia/Taipei），`python tests/run_many_groups.py` 通過。新增 3 項測試使用真正本機 HTTP、獨立暫時 SQLite 與同步起跑屏障，不直接呼叫 submit 代替 HTTP。原有 34 項測試與應用程式未修改，本輪未重跑原有測試。
- 30 組 × 6 題 × 3 輪：540 筆答案全部保存，每組每題僅一筆；每輪全部 30 組的結果 JSON 與教師一致。結束前每組只取得本組六筆，沒有其他組別或勝者資料。
- 贏家比對：依教師紀錄的最小伺服器序號及各送出回應收件時間核對；另先送入已知贏家，再由其餘組別競爭，確認偽造用戶端時間不能取代先收到者。
- 同組 30 個不同答案同時競爭：1 筆成功、29 筆 409；再重送 30 次相同答案，紀錄數與時間均不變。
- 結束與 30 組送出競爭：最新執行有 1 筆於結束前被接受，其餘拒絕；再送 30 筆結束後答案全部拒絕，已公布結果不變。先前同測試也觀察到全部先於結束送達，均按伺服器實際順序核對，不預設固定競爭勝者。
- 畫面驗收另建 30 組、6 題、180 筆；實際開啟教師 + 3 組代表學生分頁，其餘學生以 HTTP 模擬。每題先由不同指定小組送出，再由其餘 29 組同時送出，六題預期勝者為測試組 01、06、11、16、21、26，全部畫面一致，避免只驗證同一組六連勝而漏掉題號套錯問題。
- 核對老師全部 180 格答案、組別、題號及時間，3 組學生的本組六筆與結束前隱私、結束後六題贏家／答案，以及 390px 學生畫面。JavaScript 未處理錯誤 0 個。
- 瀏覽器實測開始同步 575ms、結束同步 578ms、最後一筆收件至老師顯示完整表格 355ms；皆小於 2 秒。HTTP 測試整體請求 P95 1532.4ms、最大 2055.1ms，與瀏覽器顯示同步測量是不同指標，不能混用。
- 結果：`output/playwright/many-groups-summary.txt`、`many-groups-report.json`；已視覺檢查 `many-groups-teacher-results.png` 及 `many-groups-student-results.png`。老師表格保留橫向捲動，手機結果無整頁橫向溢出。
- 測試服務與專用瀏覽器已由執行器關閉，未修改使用者正在執行的服務／正式活動，也未讀取 Google 憑證或寫入雲端表。本機模擬不等於 30 台實體裝置或校園網路負載保證。

## Git publication verification

2026-11-16 使用者指定 GitHub 儲存庫 `Jiruiii/software_project` 後，首次將本機既有成果建立 Git 紀錄。原先本機沒有 `.git`，遠端查詢也沒有任何 refs；不回填歷史日期、作者或假 PR。按環境、規格、核心服務、Google 整合、介面、多人測試、文件分為七個提交。

- 核心程式的提交快照只包含該階段 Git index 內容，匯出到獨立暫時資料夾執行測試，不借用尚未提交的未追蹤檔案：核心服務 9 tests、加入 Google 模組後 30 tests、加入 HTTP／介面後 34 tests、加入多人驗收後 37 tests，全部通過。最終 37 項執行耗時 35.445 秒。
- 初次入庫規劃文件保留目前 tasks 狀態，不偽裝成開發前文件；commit 說明與 README 明示這是實作後的分組整理。主規格尚未 sync，change 尚未 archive，雲端不同版面驗收仍保持待辦。
- GitHub 可見的測試快照位於 `docs/evidence/`，直接複製已執行的多組報告及老師／學生截圖，只有合成測試資料。原 `output/` 仍排除。
- `.gitignore` 排除 credentials、data、tmp、output、權杖、私鑰、編輯器個人設定及使用者原始 DOCX。對預計上傳檔案比對本機 OAuth client ID／secret 及常見金鑰格式，僅輸出通過與否，不印出真實值。

## Source evidence

需求來源：使用者功能清單 DOCX、七頁《期末專題說明(大學部).pdf》及五頁《期末專題說明.pdf》。五頁版本第 2 頁包含單題與題組 Google Sheets 連結，允許使用佔位符動態定位；不能因七頁版本無超連結而判定範本不存在。

- 官方單題表 ID：`12uh5xhIx2wXFMy42KU8lN7rLFQ8GDugt9zfAFEvu-1E`，一張「學習單」，六題。
- 官方題組表 ID：`1PXXwWiBKJNpPkLRoJLMzZWsAh4Jzn2bThHTeRAiq3Hg`，同題號跨列及子題標記。核心版本明確拒絕 E-09。
- 唯讀下載快照及來源說明位於 `tests/fixtures/`，用於回歸；不宣稱範本為本專案創作。

## Feature traceability

| 編號 | 實作 | 主要證據 | 狀態 |
| --- | --- | --- | --- |
| F-01 | QuizService.login/_auth；app.py；角色介面 | test_f01_roles_auth_and_logout、HTTP 越權、四分頁登入 | 本機通過 |
| F-02 | QuizService.join | test_f02_normalized_groups_and_isolation、同組分頁 | 本機通過 |
| F-03 | SheetsWorkflow.preview/import_activity；create_from_source | 實際公開表六題、預覽／原子失敗／權限測試 | 公開表通過；私人 Google 實測待辦 |
| F-04 | guided_notes.parse_grid/from_xlsx/from_google | 官方表、列欄移動、替代欄序、標記／重複／模糊、移動版面模擬往返 | 本機與公開表通過；雲端不同版面往返待辦 |
| F-05 | QuizService.transition；教師開始 | phase_gates、536ms 實測 | 本機通過 |
| F-06 | transition/submit 共用鎖 | 結束競爭、HTTP late answer、學生欄位關閉 | 本機通過 |
| F-07 | snapshot 教師視圖；renderMonitor | HTTP 全組答案／時間、teacher-active.png | 本機通過 |
| F-08 | snapshot 結果；renderResults | HTTP results、teacher-results.png | 本機通過 |
| F-09 | GoogleConnection；SheetsWorkflow.export；prepare_export | 模擬原 ID、stringValue、欄位遮罩、格式保留、衝突、權限、寫後核對及重送；使用者回報單題實際寫回成功 | 單題手動通過；不同版面與完整格式獨立核對待補 |
| F-10 | submit 伺服器階段檢查 | API 409、學生開場禁用 | 本機通過 |
| F-11 | answers 唯一約束；submit | first_answer_immutable、同組分頁同步 | 本機通過 |
| F-12 | 結果階段學生視圖 | 兩組看到贏家與無人作答 | 本機通過 |
| F-13 | snapshot/submit 資料過濾 | 他組與全域答案 id 不回傳；Sheets source 不回傳學生 | 本機通過 |
| F-14 | 鎖內伺服器順序／答案 id | 20 組併發、偽造時間無效、分頁勝者一致 | 本機通過 |
| F-15 | public/app.js refresh/poll | click 至 DOM 開始 536ms、結束 867ms | 本機通過 |

額外支援要求「建立可驗證的活動」由 test_validation_and_atomic_create 驗證；「基本紀錄保存」由 test_persistence_and_session_expiration 及瀏覽器重新整理驗證。15 個 requirement 與 15 個 F 編號非一對一，兩者分別核對。

## CRITICAL

1. 工作 3.4 部分完成：本機 Desktop 設定檔類型已檢查，使用者已完成授權、匯入並回報單題寫回成功。仍需以另一份先移動列欄的副本往返核對，記錄原 Sheet ID、成功答案、無人作答格與其他內容／格式保留。未獨立檢視雲端結果，不將使用者回報或模擬結果擴大為全部情境通過。
2. 工作 4.1 未完成：本機回歸、對照與格式檢查已執行，仍須在 3.4 完成後補齊真實情境並做最後核對。目前不 sync／archive。

## WARNING

- Sheets API 無法將讀取檢查與後續寫入組成比較交換；若他人在兩者之間移動列欄，前後核對只能偵測部分衝突。README 與匯出介面明示寫回期間不要同時編輯。這是已記載限制。
- 公開 XLSX 無 Google sheetId，首次公開匯入先保存試算表 ID、工作表名稱、內容與結構指紋；首次授權寫回再保存 Google sheetId。需要嚴格工作表身份確認時，先連線 Google 再匯入。

## SUGGESTION

無額外建議；維持使用者選定的 15 項核心範圍。

## Final assessment

2 項 critical 未完成任務，完成前不能歸檔。2 項已知限制已明示，0 項額外建議。Google 單題寫回已取得使用者手動成功回報；不同版面雲端往返及完整來源／格式比對仍缺證據。目前結果不代表所有核心功能已完成最終驗收。
