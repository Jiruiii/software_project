# Design

## Context
reference_answer 已保存於 question_meta，reference API 僅允許結果階段，表單藏於更多工具。背景同步使用已關題成功答案簽章與 last_export 保護來源格。

## Goals / Non-Goals
重用既有參考答案與同步管線，將老師補充答案與學生評分分開；不改變學生成功者或單選預設答案鍵。

## Decisions
- 新增 question_meta.reference_override 布林欄位，預設關閉且可重複遷移。reference API 以 _reviewable 控制時機，嚴格檢查選項與非空答案；手動題號活動只能存參考答案。
- 共用 _sheet_answers 合併成功者文字與已勾選的老師答案；export_context、record_export、失效檢查均沿用同一來源。學生結果依舊取 _winner_rows，不假造老師組別。
- 逐子題覆蓋。未勾選子題維持同一最快完整組，不強迫老師填滿整個題組。取消覆蓋回到候選或原值，保留既有外部編輯保護與同步失敗重試。
- 移除更多工具中的舊表單，主要工作區放可收合的「老師正確答案（選填）」與已關閉題目選單。當前題優先，已關題可選回。未儲存草稿以活動與題號保留，輪詢只更新非髒表單；儲存用一次 API 明確送出答案與選項。
- teacher snapshot 提供參考答案及覆蓋設定，學生仍只在整場結果階段取得報告參考答案。

## Risks / Trade-offs
老師文字更新與背景寫入競爭 → 共用既有簽章重新核對；空白勾選 → 拒絕並提示；儲存失敗 → 保留草稿；跨教師修改 → 非髒欄位同步，髒欄位保留本機編輯直到明確儲存。

## Migration Plan
啟動時增量新增預設關閉欄位，舊參考答案原樣保留且不意外覆蓋學習單。重啟後沿用 SQLite 設定，Google 仍須重新連線。
