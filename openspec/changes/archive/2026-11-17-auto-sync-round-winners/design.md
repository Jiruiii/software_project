# Design

## Context
SheetsWorkflow.export 已具來源結構、目標格與寫後核對及單一 export_lock。授權只保存在 GoogleConnection 記憶體且依教師登入分離。服務 tick 負責倒數關題。

## Goals / Non-Goals
每輪結束與候選變更自動收斂到最新學習單內容，不阻塞 HTTP 作答。保留內部 pending 以表示未批改簡答，但教師不能主動設為此狀態。

## Decisions
- export_context 只選 _reviewable 題目的成功者；準備中與沒有已關閉題目仍不能寫回。record_export 使用相同候選範圍核對。
- 增加 SheetsAutoSync 背景協調器，以教師開啟活動／操作綁定記憶體登入與授權，定期比較已關題與候選文字簽章，只有變更才寫回。網路執行不持有課堂服務鎖。
- 同步狀態存於服務記憶體，last_export 仍存於原資料庫。已核對成功後才標完成；資料競爭回到待同步。失敗停止該簽章自動重試，教師可重試；重新授權可重新排入。
- 工作執行緒由 HTTP server 管理，關閉時停止且等待完成後才關閉資料庫。Google 讀寫仍有原本逾時。
- 記憶體綁定不覆蓋另一位已連線教師的有效授權；不把 raw token 或 Google grant 存到資料庫或回傳瀏覽器。
- 同一活動的同步與手動重試共用 export_lock；保留來源外部修改檢查。其他活動若也指向同一格，原有衝突檢查仍拒絕互相覆蓋。

## Risks / Trade-offs
Google 寫入成功但讀回失敗 → 明示失敗，重試先核對現值，不能盲目覆蓋他人修改。重啟後授權不保留 → 提示重新連線並開啟活動。簡答未批改仍可作最快候選，但不等於已判對或加分。

## Migration Plan
無新資料庫欄位，既有來源及 last_export 沿用；前端更新同步提示並移除未判定操作。
