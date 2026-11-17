# 老師操作簡化與畫面驗收

日期：2026-11-17（Asia/Taipei）；變更：`simplify-teacher-workflow`。

## Summary

| 面向 | 結果 |
|---|---|
| Completeness | 3 項任務完成；4 個需求皆有實作 |
| Correctness | 4/4 需求與 4/4 規格情境具備瀏覽器證據 |
| Coherence | 沿用既有 API 與 DOM，切換工作區保留設定；沒有資料遷移或新增外部服務 |

## Visual review

先實際登入隔離測試活動，保存 `teacher-before-dashboard.png` 與 `teacher-before-prepare.png`，再實作、截圖與逐張目視檢查。

| 原問題 | 修正與最後畫面 |
|---|---|
| 首頁同時展示兩種建立方式、歷史區被拉高 | 來源切換、題數快速建立、活動清單獨立高度；`teacher-ui-dashboard-desktop.png`、`teacher-ui-dashboard-mobile.png`、`teacher-ui-import-desktop.png` |
| 準備頁把設定、作答表、分析堆成長頁 | 依階段顯示工作區，頂部集中代碼與操作；`teacher-ui-settings-desktop.png`、`teacher-ui-questions-desktop.png`、`teacher-ui-questions-mobile.png` |
| 批改表太寬、長答案把按鈕推到底部 | 可選題篩選；答案區可獨立捲動，批改按鈕留在可操作範圍；`teacher-ui-monitor-desktop.png`、`teacher-ui-monitor-mobile.png` |
| 結果、排行及各工具緊貼，手機總分被擠出視野 | 結果獨立工作區、長答案摘要可展開、三欄排行完整呈現、工具可收合；`teacher-ui-results-desktop.png`、`teacher-ui-results-mobile.png`、`teacher-ui-tools-mobile.png` |

桌面驗收寬度 1280 px，手機 390 px。所有 11 張新版截圖均檢查整頁水平溢出；手機排行另檢查三欄無需水平捲動。設定畫面中的錯誤提示為刻意輸入無效秒數後的驗收情境。

## Requirement mapping

- 簡化建立活動：`public/app.js` 的建立處理、`setCreateSource`、`syncQuestionInput`。驗證題數 3、自訂 A／B、非法題數、切換建立方式保留內容。
- 階段式教師工作區：`renderTeacherWorkspace`、`syncMonitorFilter`、`renderMonitor`。驗證準備／作答／結果預設、切換保留設定、逐題跟隨及手動篩選保留，透過新入口操作批改、參考答案、重播與歸類。
- 開始前儲存與錯誤定位：`saveAllSettings`、`withSettingsLock`、題目表單的驗證及提交。驗證一次儲存、直接開始先儲存、缺正解定位、非法秒數不開始；模擬 HTTP 500 時維持準備中，移除故障後可重試。多個題目的儲存沿用多次 API；失敗前已成功的設定保留，未宣稱整場原子儲存。
- 可閱讀與可操作版面：`public/style.css`、長答案展開及監看捲動區。驗證長組名、700 字以上答案、手機批改與完整答案閱讀。

## Test evidence

- `tests.txt`：完整 63 項 Python 測試通過。
- `teacher-ui-report.json`：新版老師流程與截圖驗收通過。故障測試故意回傳一次 500，預期可見網路錯誤，但沒有未處理的 JavaScript 例外。
- `question-types-report.json`：四種題型／下注組合、草稿、即時分數與批改同步通過。
- `extras-report.json`：原 E-01～E-11 瀏覽器回歸通過，改為點選新工作區入口。
- `many-groups-report.json`：30 組 × 6 題 × 3 輪共 540 筆 HTTP 作答，另有教師與三個學生瀏覽器分頁；教師核對 180 格，階段同步及答案顯示正常。
- `node --check public/app.js` 與 `openspec validate --all --strict` 通過。

## Assessment

CRITICAL：0；WARNING：0；SUGGESTION：0。完成需求、設計、實作與測試對照，沒有略過的規格核對項目。

所有驗收使用隔離活動，不修改使用者正式資料。Google 匯入入口已做畫面檢查，既有 Sheets 服務測試通過；本次未重新登入真實 Google 帳號或操作雲端試算表。多人測試是本機模擬，並非公網負載或 30 台實體裝置測試。
