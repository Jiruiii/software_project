# Proposal

## Why

師生需要從不同網路進入同一份課程資料。現行 Google Sheets 授權依附教師工作階段，登出或服務重啟會中斷寫回。

## What Changes

- VM 定期讀取 GitHub 的 main，將成功推送的網站版本自動部署，並保留目前資料與憑證。

- 將網站部署在 Azure 單一 Linux VM，以 HTTPS 使用既有 Firebase 專案登入，搬移現有 SQLite 課堂資料。
- 教師在副本開放「知道連結的任何人」編輯，從授課頁貼網址。網站匯入時記錄課程，沿用原本的私人副本授權方式。
- 題組寫回沿用搶答的整組候選資格與收件順序。保留原格定位、格式及衝突保護，服務重啟後能找回待處理工作。
- 支援老師的兩種作答區版面，區分單題作答格與題組中子題編號右方的作答格。

## Capabilities

### New Capabilities

- `classroom-hosting` 管理固定 HTTPS 入口、持久化資料及還原驗收。

### Modified Capabilities

- `guided-notes` 雲端模式使用伺服器授權及試算表共用權限，獨立於教師瀏覽器與登入工作階段。

## Impact

涉及 HTTP 來源檢查、Sheets 連線及背景同步、教師操作介面、部署設定及操作文件。保留本機操作方式。
