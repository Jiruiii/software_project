# Design
## Context
學生快照目前僅在結果階段包含 references；學生題目卡由 updateInputs 更新，結束後改顯示本組報告。寫回內容集中於 _sheet_answers，last_export 保存實際寫入字串。
## Goals / Non-Goals
讓老師儲存的已關題參考答案即時公布，並讓學習單答案可辨識來源；不公開未關題參考答案或選擇題答案鍵，不改學生作答與評分。
## Decisions
- 快照使用 _reviewable 過濾學生 references，教師仍取得完整資料。學生題目卡加入獨立「老師正確答案」區，以 textContent 顯示並隨輪詢更新，尚未填寫不顯示。
- _sheet_answers 僅於匯出邊界附加全形括號來源：組名原文或「老師答案」。相同文字由不同組遞補時，簽章也會變更。資料庫原始答案、參考答案、CSV 與畫面結果保留原文字及既有組名欄位。
- 已有 last_export 原樣作為安全比對，首次同步可將舊無註記內容更新為新格式；全錯仍還原原值，不附上來源標示。
## Risks / Trade-offs
組名與答案含特殊符號 → UI 以文字節點、Sheets 以 stringValue 寫入；老師清空參考答案 → 下次輪詢移除公布區；學生未作答 → 仍能看已公布參考答案。
## Migration Plan
無資料庫欄位變動；重啟與重新連線後沿用 last_export 核對並更新學習單標示。
