# 題型與可選下注介面

`POST /api/activities/{活動 id}/question-settings` 僅教師在準備中可呼叫。

多選使用 `type: "multiple"`、`options` 與 `correct_indices`（至少一個相異的有效索引，例如 `[0,2]`）。學生以選項文字陣列送出答案，例如 `["丙","甲"]`；題組的對應子題也使用陣列。順序不影響判分，漏選或多勾均判錯；空白、未知與重複選項會拒收。結果依題目原順序每行顯示一項。

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

各子題可帶 `prompt` 設定題目文字；省略保留原值，傳空字串清除。有表頭的學習單會從「題目」欄預填。教師狀態含完整 `question_settings`；學生可見題型、選項與下注開關，該題開放後才取得 `prompt`，不含 `correct_index`。

學生狀態另含 `own_score: {"total": 0, "pending_units": 0, "awaiting_close_units": 0}`，由登入身分綁定的本組答案計算。`pending_units` 是已關題而待批改的單位數，`awaiting_close_units` 是已送出、等待關題公布的單位數。題組有錯即扣押注分、全部正確才加分，其餘等待人工批改。新制每個單位前三組全對另加 4、2、1 分；`own_points` 回傳已公布的 `wager`、`speed`、`total`。

作答中的師生快照另含 `top_five`，最多五列，每列提供 `rank`、`group_name` 與 `score`。名次依本場已公布總分計算，逐題模式關題後計入，全題模式在該單位手動關閉或整場結束時公布。結果階段以 `scoreboard` 提供完整排名。

## 全題模式的跨場保底

全題模式的 `POST /api/activities/{id}/settings` 可傳同課程已結束活動的 `priority_source`。送出 `null` 或省略時，使用全班同時開始；逐題模式使用原有 `fairness`。授課老師的準備中活動快照提供 `priority_sources` 選項與 `settings.priority_source`。開場後學生依 `round.own_priority`、`round.priority_until` 及 `available_questions` 顯示本組可作答的題目。時間採伺服器的 Unix 秒數。

## 課程紀錄、排行與本場討論

帳號端點以 Firebase ID token 作為 Bearer 憑證，送出 JSON。活動端點使用進入該課程活動時取得的工作階段 token。

| 請求 | 傳入與回傳 |
| --- | --- |
| `POST /api/account/course` | 傳入 `course`。學生取得活動清單與本組累積總分。教學人員以 `staff: true` 讀取獲授權課程。 |
| `POST /api/account/history-detail` | 傳入 `course`、`aid`。學生讀本組紀錄，授課老師與受邀助教可加 `staff: true` 查各組的作答與批改歷程。 |
| `POST /api/account/leaderboard` | 傳入 `course`，回傳 `rows`，每列含 `rank`、`group_name`、`score`。授課老師和助教可查自己負責的課程，學生可查已加入的課程。教學工作區傳入 `staff: true`；伺服器會重新確認本課教學權限。 |
| `GET /api/activities/{aid}/chat?after=0` | 本場有頻道權限的學生可取 `messages`，每筆含 `id`、`group_name`、`body`。後續用最後一筆的 `id` 取下一批，每次最多 100 筆。 |
| `POST /api/activities/{aid}/chat` | 傳入 `body`（1～500 字）與 `request_id`。小組署名取自登入身分，同一小組重送相同請求及內容時只保留一份。 |

學生快照的 `chat_available` 表示本場是否可討論。整場結束會刪除該場訊息，結束後的歷史資料仍可從課程紀錄查詢作答與判定。

## 手動題組、關題與批改紀錄

| 操作 | 請求與結果 |
| --- | --- |
| 建立活動 | `POST /api/activities` 除了既有 `title` 與 `questions`，可傳 `groups: [{"id":"1","questions":["1.1","1.2"]}]`。子題須列於原題號陣列，母題獨立命名，未分組的題號各自收件。 |
| 備課參考答案 | `question-settings` 的各子題可傳 `reference`，空字串清除，省略則保留。連結 Sheets 時可連同文字傳入布林值 `reference_override`，於關題後採用老師答案。`reference` API 可在備課或關題後儲存。學生快照只含已關閉題目的參考答案。 |
| 全題個別關題 | `POST /api/activities/{id}/close-question` 傳入 `question`。如為子題，同一單位全部關閉。快照的 `closed_questions` 顯示已關題號。 |
| 改回待判 | `POST /api/activities/{id}/review` 傳入 `answer_id`、目前 `revision` 與 `verdict: "pending"`。 |
| 查詢與復原 | `GET /api/activities/{id}/review-history` 傳回自己的 `batches`。用 `review-undo` 傳入 `batch_id` 復原，伺服器會再次驗證每筆版本。 |
| 移除助教 | 課程老師用 `POST /api/account/remove-assistant` 傳入 `course`、`uid` 與 `confirmed: true`。本課助教可在授權期間使用既有 `leaderboard`。 |
