# Verification Report

## Summary

| 規格或設計 | 證據 |
| --- | --- |
| 逐題模式每次開題依本場最低分決定資格 | 修改前重跑 `test_extras.py` 的三項 E-02 測試及 `test_review_flow.py` 的三項 FairnessReviewTests。修改後亦於應用回歸通過。 |
| 全題選來源與課程權限 | `course_accounts.py` 列舉、驗證同課程已結束的場次。`test_source_choices_and_permissions` 驗證跨課程、進行中、助教、學生、切換模式及清除設定。 |
| 小組身分、並列與開場快照 | `prior_priority_groups` 以兩場 attendance 對應固定 team。`test_ties_identity_absences_regrade_restart_and_boundary` 以另一名成員進入更名小組，並讓新組使用原名稱，驗證負分並列、缺席、晚到與重啟。 |
| 作答門檻與時鐘 | `QuizService.transition` 保存開場時間、名單及期限，`_submission_gate` 處理每道單題與題組。`test_cross_activity_priority.py` 五項通過，含 2.999 秒、恰滿 3 秒、手動結束、較短作答時限、開始前後改判，以及沒有共同小組的情形。 |
| 教師與學生畫面 | Chrome 執行 `tests/browser-cross-priority.js` 兩次通過。教師選擇、儲存、重新整理並切換模式；兩個學生分頁分別驗證先答與等待提示，等待的小組於期滿後成功送出。使用測試身分及記憶體 SQLite，瀏覽器請求透過程序管道交給實際 Python HTTP handler。 |
| 資料庫相容性 | 以暫存 SQLite 移除新增欄位後重新啟動。舊版進行中全題活動保留答案，沒有等待期，仍可繼續作答。 |

## Regression

以記憶體傳輸連結 Python HTTP 用戶端及實際 handler，排除需要 Git 子行程的三項部署測試，138 項應用測試全部通過，包含 30 組併發與 Firebase 測試權杖簽章。

修改前原生完整測試執行 136 項，回報 19 筆錯誤及 1 項 Firebase 相依套件缺失而略過。Windows 拒絕測試程式連回本機監聽埠（WinError 10013），並拒絕部署測試的 Git 子行程建立 MSYS 物件。以另一套 Git 重跑三項部署測試亦收到相同作業系統錯誤。正式站與 Azure 部署不在這次驗收範圍。

修改後以本機既有的 google-auth 套件重跑 141 項，19 筆錯誤的測試及子案例名稱與基線完全一致，無略過。新增的五項測試皆通過。環境受限的 TCP 與 Git 部署測試未列為通過。

## Assessment

兩項規格共九個情境均有實作與測試證據。依據場次結束時間排列來源、以固定小組比對、交易內保存快照及共用收件門檻均符合設計。變更與八份主規格已通過 OpenSpec 嚴格驗證。
