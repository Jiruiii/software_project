# 額外功能驗證報告

日期：2026-11-16；變更：add-classroom-extra-features。

## Summary

| 面向 | 結果 |
|---|---|
| Completeness | 12/12 任務完成；18 個新增／修訂需求均有實作 |
| Correctness | 核對 33 個情境；55 項自動測試、額外功能瀏覽器驗收、多組壓力驗收及真實 Sheets 往返通過 |
| Coherence | 沿用 SQLite 交易與鎖、角色隔離、動態定位；遵循使用者確認的保底、下注及參考答案規則 |

## Requirement mapping

| 需求 | 實作 | 驗證 |
|---|---|---|
| E-01 CSV | quiz_extras.py activity_csv；app.py csv 路由 | test_extras CSV 權限、公式防護、收件順位；瀏覽器下載 |
| E-02 保底 | quiz_extras.py configure、_open_round、_close_round、_submission_gate | 三題門檻、三秒邊界、晚加入、重複關題、未關先開拒絕、舊資料遷移 |
| E-03 重播 | public/app.js renderReplay、replayTick | 選題、暫停、繼續、空題、學生隔離、播放前後紀錄相同；資料順序由伺服器 id 保證 |
| E-04 下注 | quiz_service.py submit、quiz_extras.py _unit_points | 1～3 整數、非法值、相同重送、不同下注拒絕、重判重算 |
| E-05 遞補 | quiz_extras.py review、_winner_rows；quiz_service.py export_context、record_export | 權限／階段、判錯遞補、撤銷、全錯無成功者、原時間保留、寫回後判錯還原及寫回途中改判 |
| E-06 歸類 | quiz_extras.py clusters | 全半形、空白、大小寫、相近字串、原文不變、學生不能讀取；程式檢查 200 代表後僅精確比對 |
| E-07 報告 | quiz_extras.py _report、report_csv | 本組資料、負分、未作答、參考答案、CSV 公式防護及跨活動隔離；瀏覽器下載 |
| E-08 恢復（F-15） | public/app.js 草稿與 refresh | 重新整理恢復文字及下注、斷線重連、收件後丟棄回應、登出清除 |
| E-09 題組 | guided_notes.py parse_grid；quiz_extras.py submit_unit | 官方兩題組＋兩單題、移動列欄、缺漏／空白拒絕、20 組併發完整提交、整組遞補、整組草稿與真實原位寫回 |
| E-10 排行 | quiz_extras.py _scoreboard | 零分、負分、同分名次、改判不累加、未結束不公布、題組一次計分 |
| E-11 倒數 | quiz_extras.py tick、expire_first；app.py TimedServer | 期限前後、逐題關題、最後一題結束、無瀏覽器到期、重啟期限保存、0 不限時及瀏覽器自動轉結果 |
| 教師參考答案 | quiz_extras.py reference | 結果階段與教師權限、儲存／清空、學生同步、原答案不被覆寫 |
| F-05／F-10 門檻 | quiz_service.py transition、submit | 開始前／結束後拒絕、模式／保底／期限驗證及畫面同步 |
| F-11 組別提交 | quiz_service.py submit；quiz_extras.py submit_unit | 身分由 session 決定、首筆鎖定、空白與不存在題目、題組原子性 |
| F-14 順位 | quiz_extras.py _winner_rows | 30 組競爭、同組衝突、伺服器時間、唯一成功者、判錯後遞補 |
| F-08／F-12 結果 | quiz_service.py snapshot；public/app.js renderResults | 各角色結果一致、無人作答與全錯區別、學生不含非成功的他組答案 |
| F-04 定位 | guided_notes.py parse_grid | 單題／題組、不同列欄、合併格、佔位符、不完整與重複布局拒絕 |
| F-09 寫回 | guided_notes.py prepare_export；google_sheets.py export | 原表識別、純文字公式、格式／無關內容保留、來源變動拒絕、官方表保護、重新判定寫回 |

## Evidence

公開證據位於 `docs/evidence/extras-2026-11-16/`：

- `unit-tests.txt`：55 項測試通過，11.875 秒。
- `browser-report.json`：E-01～E-11 介面操作全部通過，無頁面例外。
- `many-groups-report.json`：HTTP 模擬 30 組 × 6 題 × 3 輪，共 540 筆；另以教師＋3 學生實際分頁核對 180 個答案格。開始同步 585ms、結束 569ms、教師答案顯示延遲 459ms。
- `live-sheets-report.json`：真實 Google 驗收於 14:37～14:38 UTC 完成，包含單題原版、單題移動列欄、佔位符、題組原版、題組移動列欄；每份版面比較無關內容與格式雜湊一致。後續寫回途中改判處理另以模擬 API 測試驗證。
- `teacher.png`、`grouped-student.png`：教師與手機寬度學生畫面；表格可左右捲動，頁面無水平溢出。

不保存 OAuth token、用戶端憑證或私人試算表連結至公開證據。

## Findings

無未處理的 CRITICAL／WARNING，無跳過的適用驗證面向。33 個情境由上表測試與程式核對涵蓋；不是宣稱每個情境各有一支獨立測試。

整合驗收修正：舊測試改為排除會前進的 server_time 後比較固定紀錄；同時連線佇列調整為 128，30 組尖峰不再偶發拒絕連線；公布結果明確區分無人作答與被判錯；離開活動停止重播；Google 寫回中改判會要求重新寫回。

已知邊界沿用原專案：本機可信課堂、組名不是帳號驗證，尚未公網部署；多人測試為本機模擬，不是 30 台實體裝置。Google 外部編輯不是跨系統原子交易，仍需避免寫回期間移動或修改來源表。相近文字不是語意或正確性判斷。

全部檢查通過，可同步正式規格並歸檔。

## Archive

正式規格已同步，嚴格驗證 5/5 通過，12/12 任務完成後歸檔。CLI 另有非阻擋建議「超過 10 個 delta 可考慮拆分」；本次保留同一份整合規格，E-01～E-11 的實作仍各自獨立提交，便於逐項追蹤。
