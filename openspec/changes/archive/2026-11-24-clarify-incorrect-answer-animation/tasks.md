## 1. 單筆判錯回饋

- [x] 1.1 調整領先組判錯的動畫區、組名、踢擊時序與靜態結果。
- [x] 1.2 以瀏覽器驗證桌面與手機的尺寸、認讀停留、結束結果、連續操作與減少動態，執行相關回歸測試。

## 驗收紀錄

- 本機 Chrome 以桌面與 390px 寬度驗證紙張在第 400 毫秒仍靜止、球鞋在第 900 毫秒接觸紙張，以及動畫結束時判錯組與遞補文字可見、回饋區高度固定。視覺紀錄存於 `docs/evidence/classroom-motion/incorrect-answer-feedback.gif`。
- `browser-motion.js`、`browser-review-flow.js`、`browser-batch-review.js` 通過，含播放途中復原、鍵盤焦點、減少動態、跨活動隔離與批次批改。
