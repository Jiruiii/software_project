# 測試與驗收

在專案資料夾執行完整測試：

```powershell
python -m unittest discover -s tests -v
```

在已安裝 `requirements-firebase.txt` 的 Python 環境執行。瀏覽器驗收使用隔離資料庫與測試身分。

- 帳號工作區、課程加入、密碼重設、排行榜、聊天與代碼複製：`python tests/run_extra_ui.py --suite courses`。
- 手動題組、預填、全題個別關題、助教改判、跨工作階段批次復原、回放倍速與撤權的 Chrome 流程：`python tests/run_extra_ui.py --suite classroom-operations`。對應的資料升級與衝突測試：`python -m unittest discover -s tests -p test_classroom_operations.py -v`。
- 全題跨場保底：`python -m unittest discover -s tests -p test_cross_activity_priority.py -v`。教師選來源、重新載入設定及兩組學生在三秒前後的作答介面，可用 `python tests/run_extra_ui.py --suite cross-priority` 驗收。
- 多選題、完整吻合判分及草稿恢復：`python tests/run_extra_ui.py --suite multiple`。
- 題型、不押及本組即時分數驗收：`python tests/run_extra_ui.py --suite question-types`。

老師操作與桌面／手機截圖驗收：`python tests/run_extra_ui.py --suite teacher-ui`。

額外功能的瀏覽器驗收：`python tests/run_extra_ui.py`（涵蓋逐題、下注、判分、重播、報告、斷線、題組、排行及倒數）。

要測試多組同時搶答，可雙擊 `test-many-groups.cmd`，或執行：

```powershell
python tests/run_many_groups.py
```

會模擬 30 組、6 題、連續 3 輪，並核對老師與學生畫面。瀏覽器測試需要 Node.js、Chrome，以及可下載測試工具的網路；若只跑服務測試，可使用 `python tests/run_many_groups.py --http-only`。

測試會使用獨立暫存資料，不影響正在使用的活動或 Google 試算表。中文結果位於 `output/playwright/many-groups-summary.txt`。

## 真實 Google Sheets 驗收

完成 Google 首次設定後，雙擊 `test-google-sheets.cmd`，或執行：

```powershell
python tests/run_live_sheets.py
```

1. 在自動開啟的瀏覽器完成 Google 授權；不需要先啟動主程式或輸入教師密碼。
2. 工具會在該帳號建立一份「課間－自動驗收」試算表，複製官方範本並建立不同版面的測試工作表；只修改這份新建表，不改動官方範本或既有活動。
3. 自動驗證匯入、兩組作答、原位寫回、純文字答案、格式保留、無人作答、重複寫回，以及來源移動後拒絕寫回。
4. 結果位於 `output/live-sheets/report.json`，測試表連結位於 `output/live-sheets/test-workbook.txt`。測試表保留供人工查看，可自行刪除。

這項測試會實際讀寫 Google，與前面的離線自動測試不同。授權最多等待 10 分鐘；每次執行需要重新授權，權杖只存於記憶體，結束後清除。測試表不會自動公開分享。

## 驗收紀錄

2026-11-22 發布前重新執行完整單元測試，127 項通過；`courses` 瀏覽器流程使用離線身分通過。OpenSpec 嚴格驗證通過 8 份主規格與 1 個進行中的變更。

歷史測試資料保存在 [驗收證據目錄](evidence/README.md)。近期排行榜、學生公用頻道、可複製代碼的測試結果記在各自的 [OpenSpec 歸檔](../openspec/changes/archive/)。Firebase 真實帳號驗收請見[帳號整合驗收紀錄](../openspec/changes/archive/2026-11-25-firebase-course-accounts/tasks.md)。

2026-11-26 已驗收七項課堂操作。新增的 Chrome 流程以三組學生與兩門課串接備課、提交、部分關題、助教批改、跨工作階段復原、回放及撤權。完整 Python 測試共 153 項通過。使用隔離 SQLite、離線登入及 Sheets 替身。執行環境禁止連往 loopback，測試將 HTTP 請求送進相同的應用程式處理器；部署測試以本機 Git bundle 傳輸提交。未連線至正式站或修改實際試算表。
