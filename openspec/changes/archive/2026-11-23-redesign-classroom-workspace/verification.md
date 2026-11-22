# Verification Report

## Scope

在本機 Windows Chrome 與測試身分下驗收。瀏覽器使用 Playwright，課堂流程以既有測試資料及記憶體 SQLite 操作實際 Python HTTP handler。Google 登入提供者與 Sheets 使用測試替身。此輪評估前端改版，未執行正式站登入或寫入。

## Results

| 驗收項目 | 實際結果 |
| --- | --- |
| Hallmark 來源 | 逐檔比對 GitHub ZIP 的 187 個技能檔案，均相符。ZIP 註記提交為 `04977e15f3dfd6ee4b74c887dac3eb52665d6c92`，另保留根目錄 MIT 授權。 |
| 靜態檢查 | `sloplint.mjs public --scope app --render --kept` 最終為 0 FAIL、0 REFLEX、0 WARN，原清單的 6 個連結、3 個具名欄位均保留。工具不含前端動態建立的操作，另用真實瀏覽器驗證。 |
| 登入 | 改版前後都以 320、375、390、600、768、1024、1280、1920 px 瀏覽器檢查。登入按鈕在首屏可見、可鍵盤聚焦，切換教學身分後顯示對應標題。 |
| 帳號、課程及小組 | `courses` 通過。包含教師建課、學生建組及入場、複製代碼、多角色導覽、課程排名與手機選單。 |
| 教師工作台 | `teacher-ui` 通過。手動與匯入切換、錯誤定位、儲存後開始、逐題開關、監看、批改及結果，並拍攝桌面與手機畫面。 |
| 學生及批改 | `extras`、`review-flow`、`batch-review` 通過。包含組題送出、草稿與斷線恢復、答案批改、重播、學習報告、手機版面及批改撤銷。 |
| 三秒保底及同步 | `cross-priority` 雙組瀏覽器驗收、五項 Python 跨場保底測試，以及 `auto-sync` 的模擬 Sheets 寫回流程通過。 |
| 視覺複核 | 以實際截圖核對登入、教師監看、學生作答與報告。縮短桌面登入說明，長答案加捲動提示，手機作答區置前、公用頻道獨立位於左下方，寬報告改為局部橫向捲動。 |

Hallmark 的原生 render 需 puppeteer-core，本機無此套件，以現有 Playwright 驅動 Chrome 拍攝和量測。附帶 refcheck 自測建立暫存符號連結時因 Windows 權限中止；未將該項列為通過。

對照圖位於 `docs/evidence/classroom-ui-redesign/login-comparison.png`，並附教師工作台與手機學生作答截圖。
