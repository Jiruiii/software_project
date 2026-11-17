# Design

## Context
目前 answers.elapsed_ms 固定從 activities.started_at 計算；activity_options.round_started_at 只有最後一題的起點。

## Goals / Non-Goals
計時以每題開放為準，跨畫面一致；不更改收件順位、保底門檻、倒數或計分。

## Decisions
- question_meta 新增 opened_at，開題時保存所有子題同一起點，全題模式使用活動開始時間。
- answers 新增 elapsed_basis，舊資料預設 activity，新答案採 question；elapsed_ms 保留欄位名稱並儲存題目相對毫秒數。
- 啟動遷移可還原全題及舊逐題最後開放單位的起點，僅轉換有可靠 opened_at 的舊答案；之前題目缺少紀錄者保留 activity 標示。
- 前端共用計時文字函式，CSV 加計時基準欄。重播動畫間隔直接以原始 received_at 差計算，避免混合舊新基準干擾動畫。

## Risks / Trade-offs
舊逐題較早題目無法重建精確起點 → 不猜測，標示活動開始後（舊紀錄）。保底時間納入共同起點，並非每組獲准作答後獨立計時。

## Migration Plan
啟動時新增 nullable 起點欄與舊基準預設值，保留答案原文、收件時間及判定。新版本遷移可重複執行且不重算已轉換答案。
