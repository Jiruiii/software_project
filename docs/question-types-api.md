# 題型與可選下注介面

`POST /api/activities/{活動 id}/question-settings` 僅教師在準備中可呼叫。

```json
{
  "unit": "1",
  "betting_enabled": true,
  "questions": [
    {"question": "1", "type": "choice", "options": ["甲", "乙"], "correct_index": 1}
  ]
}
```

簡答使用 `type: "short"`；題組須一次提供所有子題。單選 2～8 個選項，每項 1～200 字且不重複，正解索引從 0 開始。設定儲存是整組交易，開始後拒絕修改。

原 `answers` 與 `bundle` 提交介面維持使用選項原文作為答案。`stake` 接受 0～3 整數，省略時為 0；0 為不押，關閉下注時只能是 0。單選由伺服器寫入判定，不採用客戶端提供的分數、判定或正解。簡答仍等待人工批改；重送不覆蓋原答案或已更正的判定。

教師狀態含完整 `question_settings`，學生狀態只含題型、選項與下注開關，不含 `correct_index`。舊活動仍為簡答，已儲存的下注值不變。

學生狀態另含 `own_score: {"total": 0, "pending_units": 0}`，由登入身分綁定的本組答案計算。同場活動累積，未作答單位不計入待判定，題組有錯直接扣分、全部正確才加分，其餘等待人工批改；不押分數永遠是零。活動結束前不傳他組分數及排行。
