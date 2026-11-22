# 課堂搶答系統

老師以課程為單位建立搶答活動，學生用自己的 Google 帳號加入課內小組。每場活動可使用簡答、單選、多選及題組，搭配押注、搶答加分、批改與排行榜。也可以匯入 Google Sheets 學習單，將成功答案寫回原表。

## 第一次啟動

Azure 部署與既有課堂資料搬移請參閱 [Azure 部署指南](docs/azure.md)。

1. 準備 Python 3.11 以上及 Chrome 或 Edge，依 [Firebase 帳號與課程設定](docs/firebase.md) 安裝套件並建立本機設定檔。
2. 在 Windows 專案目錄執行 `start-classroom.cmd`。啟動器優先使用專案的 `.venv`，也可以執行 `.\.venv\Scripts\python.exe app.py`。
3. 保留啟動視窗，開啟 [本機課堂](http://localhost:8000)。管理員授予教師資格後，老師即可建課，按「複製」分享課程代碼。學生登入後建立或加入該課程的小組。
4. 先停止程式再關閉啟動視窗，可在終端機按 `Ctrl+C`。用同一份資料庫重啟後，可繼續查看課程、分數與作答紀錄。

本機測試可使用不同瀏覽器設定檔登入多種身分，課堂資料存於 `data/classroom.sqlite3`。Azure 模式以 HTTPS 反向代理連到同一套服務，使用原 Firebase 專案及 VM 上的持久化資料庫。登入及 Google Sheets 同步需要網路。

## 功能與操作文件

| 想完成的事 | 從哪裡開始 |
| --- | --- |
| 指定管理員、授予教師資格、建課、邀助教、找回組名或重設小組密碼 | [帳號與課程設定](docs/firebase.md) |
| 開一場搶答、設題、保底先答、下注、查看本場或課程排名 | [師生課堂操作](docs/classroom-guide.md) |
| 小組討論、斷線回來繼續作答、結束後批改、回看歷史與下載報告 | [作答與課後紀錄](docs/classroom-guide.md#學生作答與公用頻道) |
| 準備學習單、設定多選、逐題同步、用老師答案覆寫 | [Google Sheets 學習單](docs/google-sheets.md) |
| 串接題型設定、送出答案與讀取分數欄位 | [題型與計分 API](docs/question-types-api.md) |
| 執行單元、瀏覽器、多組同時作答或真實 Sheets 驗收 | [測試與驗收](docs/testing.md) |

## 開發進度

UI 使用專案內的 [Hallmark 設計工具](skills/hallmark/SKILL.md)。在專案根目錄執行 `node skills/hallmark/scripts/sloplint.mjs public --scope app` 可檢查版面與互動樣式；實際師生操作另由瀏覽器測試驗證。

已歸檔功能的規則收在 [OpenSpec 主規格](openspec/specs/)。管理員授權、教師建課、學生建組、搶答與回查紀錄已用實際帳號測過；真實助教帳號共同批改仍待驗收。[帳號整合驗收紀錄](openspec/changes/firebase-course-accounts/tasks.md)

全題模式預設所有組別同時開始。授課老師可在活動設定選擇同課程已結束的場次，讓兩場都有參加且前場總分並列最低的小組先答三秒。[跨場保底規則](docs/account-priority-backlog.md)

## 常見問題

- **Google 登入顯示 `auth/unauthorized-domain`**　核對網址列使用的主機名稱，以及 Firebase Authentication 的授權網域設定。[本機登入設定](docs/firebase.md)
- **連接埠已被使用**　執行 `start-classroom.cmd --port 8001`，再開啟 [本機課堂 8001](http://localhost:8001)。
- **要使用舊版共用密碼入口**　尚未綁定 Firebase 的資料庫可執行 `start-classroom.cmd --legacy`。兩種入口的組別與代碼用法見[舊版測試流程](docs/classroom-guide.md#舊版共用密碼入口)。
- **要備份班級資料**　先停止程式，再備份 `data/classroom.sqlite3`。在原 Firebase 專案下使用同一份資料庫，即可保留原課程與帳號關聯。
