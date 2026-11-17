# Design

## Context
既有 review 在交易中判定單筆答案，分數由 verdict 動態推導；clusters 只回傳原文與組別。沿用 _reviewable 的題目關閉限制。

## Goals / Non-Goals
提供可撤銷的原子批改，不增加 AI、改變相似度或另存分數。

## Decisions
- 新增答案 review_revision 與持久化 review_batches 記錄，保存原判定與操作後版本。避免用前端提供的舊判定撤銷造成任意覆寫。
- 批次 API 收到題號與選取答案 id/revision，先驗證整批，再於單一交易寫入；單筆批改也遞增版本，包含重判相同結果。
- clusters 回傳 id/verdict/revision、reviewable 與每類 exact 標記。exact 僅指所有原文字串完全相同，歸類仍依原本正規化與相似度。
- UI 手動更新分類，不讓輪詢清空選取；操作後重新取分類與活動狀態。最近一次撤銷按鈕保留於該活動頁，切換活動或重新載入清除。

## Risks / Trade-offs
- 多教師同時批改 → 版本衝突拒絕整批，提示重新比較。
- 網路回應遺失 → 不自動重送，舊版本阻擋重複批改；教師重新比較確認現況。
- 長答案與窄螢幕 → 原文換行、按鈕換行，桌面及手機截圖驗證。

## Migration Plan
啟動時新增欄位預設 0 與新資料表，保留既有答案。退回舊版可忽略新增欄位；再次使用新版前須重新取得分類。
