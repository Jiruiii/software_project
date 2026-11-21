# 第一次使用 Google 帳號進入課堂

這份指南適用於管理員、授課老師、助教與學生。Firebase Authentication 負責 Google 登入，課程、小組密碼雜湊、作答及批改紀錄保存在啟動服務那台電腦的 `data/classroom.sqlite3`。若要在既有資料庫啟用帳號，請先停止程式並備份資料庫。同一份資料庫會綁定一個 Firebase 專案。

## 1. 建立 Firebase 專案

1. 用預計當管理員的 Google 帳號進入 [Firebase 控制台](https://console.firebase.google.com/)，建立專案。Google Analytics 可略過。
2. 在專案總覽選「新增應用程式」的網頁圖示 **</>**，註冊一個 Web App，例如「課堂搶答」。保留畫面上 `firebaseConfig` 中的四個值，下一步會用到。[Firebase 網頁應用程式設定](https://firebase.google.com/docs/web/setup)
3. 打開 **Authentication → Sign-in method**，新增並啟用 **Google**，選擇專案支援信箱後儲存。[Google 登入官方說明](https://firebase.google.com/docs/auth/web/google-signin)
4. 在 **Authentication → Settings → Authorized domains** 確認有 `localhost`。若實際從 `http://127.0.0.1:8000` 登入，也要加入 `127.0.0.1`。輸入主機名稱，不含通訊協定或連接埠；出現 `auth/unauthorized-domain` 時先核對此處與網址列。

## 2. 安裝套件與填入設定

在專案根目錄開啟 PowerShell，執行下列指令。之後用同一個虛擬環境啟動。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-firebase.txt
New-Item -ItemType Directory -Force credentials
notepad credentials\firebase.json
```

將下面範例的前四個值換成剛才 Web App 顯示的值。第一次先保留空白的 `adminUid`，存檔後確認檔名為 `firebase.json`。

```json
{
  "apiKey": "填入 apiKey",
  "appId": "填入 appId",
  "authDomain": "你的專案.firebaseapp.com",
  "projectId": "填入 projectId",
  "adminUid": ""
}
```

```powershell
.\.venv\Scripts\python.exe app.py
```

開啟 [本機課堂](http://localhost:8000)。這個流程使用 Web App 設定和 Google 簽名驗證，無須下載服務帳戶私鑰。Google Sheets 學習單的讀寫授權仍從老師的活動工作區設定。

## 3. 用你的兩個帳號開第一門課

1. **管理員帳號**選「老師與助教」，用 Google 登入，在「我的帳號資料」複製 UID。把它填入設定檔的 `adminUid`，按 Ctrl+C 停止程式，再執行上方啟動指令。重新整理後可在右側目錄看到「授予教師資格」與「分配舊活動」。
2. **老師帳號**用另一個瀏覽器設定檔登入，複製自己的 UID。回到管理員頁面，填入老師 UID，按「授予教師資格」。回老師首頁重新整理，即可建立課程，再把畫面上的**課程代碼**給學生。
3. **學生測試帳號**選「學生」登入。第一位組員從右側目錄選「建立小組」，輸入課程代碼、組名及至少八個字元的密碼。其他組員各用自己的 Google 帳號選「加入小組」，填相同資料。下次登入從「我的小組」直接進入課程。
4. **助教帳號**先登入一次，把 UID 給老師。老師在自己建立的課程按「加入助教」。助教登入後可查看該課程及批改；同一筆答案被別人先改判時，畫面會提示重新查看。建議用獨立瀏覽器設定檔同時測試各身分。

## 4. 找回小組與重設密碼

已加入的學生用原 Google 帳號登入，「我的小組」會列出課程與組名。若其他組員需要加入卻忘記密碼，請授課老師進入該課程，從右側選「重設小組密碼」，確認組名後設定新密碼，再交給組員。重設會保留既有成員、作答與成績。

課程代碼及「我的帳號資料」的 UID 都可按旁邊的「複製」。學生加入小組使用課程代碼；指派老師與助教則需要對方先登入並提供帳號 UID。

## 5. 驗收第一場活動

登入後系統依帳號權限開啟工作區。首頁和活動頁右上角的頭像都可以開啟「我的帳號資料」與歷史紀錄。學生在「作答紀錄」選課後可展開每一場的答案與判定。老師與助教從「學生作答與批改」選課、展開活動，可看到各組的答案、送出者與批改歷程。點「前往批改」會直接開啟該場的批改畫面。

學生首頁「我的小組」列出此帳號已加入的課程與組名。教師首頁「我的課程」列出擁有或受邀的課程，可由右側「新增課程」另建課程。點進課程後，授課老師可從右側目錄建立活動、加入助教或重設該課程的小組密碼。手機點右上角的目錄按鈕即可展開。

老師建立一場簡答活動，學生進入並送出。老師關題或結束活動後，讓助教判定正確，再由老師改判錯誤。查看原答案、兩次批改紀錄及更新後的分數。讓學生登出再登入，從「我的小組」打開同一門課，核對總分和歷次作答，再用第二門課確認分數分開。

舊版活動可由管理員逐場指定歸屬課程，老師可回看原作答。學生的個人帳號紀錄從建立課內小組後開始。若日後部署到 Azure，需提供可從學生裝置連線的 HTTPS 網址、加入 Firebase 授權網域，並把這份 SQLite 資料庫移到持久磁碟；目前服務僅監聽本機。
