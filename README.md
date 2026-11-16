# 課堂搶答系統

供老師建立活動、學生以小組搶答，並將成功答案寫回 Google Sheets 學習單。目前使用同一台電腦的多個瀏覽器分頁模擬課堂。

## 執行環境

- Python 3.11 以上，主程式不需另外安裝 Python 套件。
- Chrome 或 Edge 瀏覽器。
- Google Sheets 匯入與寫回需要網路；學生作答不需要 Google 授權。

## 啟動程式

Windows 可直接雙擊專案資料夾內的 `start-classroom.cmd`。

也可以開啟終端機執行，資料夾路徑請依實際位置調整：

```powershell
cd D:\software_project
python app.py
```

1. 依提示設定至少 **8 個字元的教師密碼**。輸入時不顯示文字是正常的。
2. 保留啟動視窗，使用瀏覽器開啟 http://127.0.0.1:8000 。
3. 選「我是老師」，輸入剛才設定的密碼。

停止程式時，在啟動視窗按 `Ctrl+C`。活動與答案會保存在 `data/classroom.sqlite3`，重新啟動後仍可查看。

不需要建立 `.env`。`.env.example` 僅列出可選的環境變數，程式不會自動讀取 `.env`；一般操作直接在啟動時輸入密碼，Google 設定檔使用下方預設位置即可。

## 測試一場搶答

1. 老師輸入活動名稱及題號，每行一題，例如 1、2、3，按「建立並進入活動」。
2. 記下畫面上的六位活動代碼。
3. 另開兩個新分頁，進入相同網址，選「我是學生」。
4. 輸入活動代碼及不同組別名稱，例如「第 1 組」與「第 2 組」。
5. 回老師分頁按「開始搶答」，學生便可送出答案。
6. 老師可即時查看各組答案與送出時間。
7. 老師按「結束搶答並公布結果」，學生會自動看到各題成功組別。

請開啟新分頁並輸入網址，避免使用「複製分頁」而帶入原分頁的登入身分。

同一活動中，相同小組名稱視為同組。每組每題只能保留第一筆答案，送出後不能修改。搶答成功依伺服器收到答案的先後順序決定，不代表答案已判定正確。

目前採可信課堂模式，組別名稱不是身分驗證；知道活動代碼的人可以輸入相同名稱加入同組。

## 使用 Google Sheets 學習單

手動建立題號可直接測試搶答；要把答案寫回試算表，請改用 Google Sheets 匯入建立活動。

### 首次設定

1. 在 Google Cloud 建立專案，啟用 **Google Sheets API**。
2. 設定 OAuth 同意畫面，將準備登入的 Google 帳號加入測試使用者。
3. 建立 **電腦版應用程式（Desktop app）** OAuth 用戶端，下載 JSON。
4. 在專案內建立 `credentials` 資料夾，將下載的檔案改名並放到：
   ```text
   credentials/google-oauth-client.json
   ```
5. 進入教師頁，按「連線 Google」→「開啟 Google 授權頁」，登入並同意試算表存取。

教師頁的「首次設定說明」提供完整操作步驟。教師登出或伺服器重新啟動後，需要再次連線 Google。

若你是組員或助教，可依上述步驟建立自己的 Google Cloud 專案與用戶端，將自己的帳號加入自己專案的測試使用者，不必由作者替你開通。也可以使用作者透過非公開管道提供的用戶端設定檔；若該專案仍為測試模式，作者必須先加入你準備授權的帳號。兩種方式都使用你自己的 Google 帳號授權，並寫入你有編輯權限的學習單。

真實 JSON、密碼與授權 token 不可放入公開 repository；下載程式不會附帶這些資料。Google 官方設定參考：[Sheets Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python)、[OAuth 同意畫面](https://developers.google.com/workspace/guides/configure-oauth-consent)。

### 匯入與寫回

1. 開啟[官方單題範本](https://docs.google.com/spreadsheets/d/12uh5xhIx2wXFMy42KU8lN7rLFQ8GDugt9zfAFEvu-1E/copy)，建立自己的副本。
2. 將副本網址貼到教師頁的「Google Sheets 連結」。
3. 按「讀取並預覽題號」，核對工作表、題數與答案格，再建立活動。
4. 讓學生加入、開始搶答、送出答案，再由老師結束搶答。
5. 按「寫回成功答案」，回到原副本確認答案已填入。

公開表可直接讀取；私人表及寫回需要老師的 Google 授權。官方原範本僅供試讀，寫回請使用自己的副本。目前支援單題學習單，尚不支援題組。

無人作答的格子保留原值。匯入後若更動題目或列欄，請重新匯入；寫回期間請勿同時編輯原表。

自訂版面可在答案格放完整標記，例如 `{{Q:1}}`。標記會在寫回時被答案取代，因此只靠標記定位的學習單，每輪請使用保留標記的未填寫副本。

## 自動測試

在專案資料夾執行完整測試：

```powershell
python -m unittest discover -s tests -v
```

要測試多組同時搶答，可雙擊 `test-many-groups.cmd`，或執行：

```powershell
python tests/run_many_groups.py
```

會模擬 30 組、6 題、連續 3 輪，並核對老師與學生畫面。瀏覽器測試需要 Node.js、Chrome，以及可下載測試工具的網路；若只跑服務測試，可使用 `python tests/run_many_groups.py --http-only`。

測試會使用獨立暫存資料，不影響正在使用的活動或 Google 試算表。中文結果位於 `output/playwright/many-groups-summary.txt`。

### 真實 Google Sheets 驗收

完成 Google 首次設定後，雙擊 `test-google-sheets.cmd`，或執行：

```powershell
python tests/run_live_sheets.py
```

1. 在自動開啟的瀏覽器完成 Google 授權；不需要先啟動主程式或輸入教師密碼。
2. 工具會在該帳號建立一份「課間－自動驗收」試算表，複製官方範本並建立不同版面的測試工作表；只修改這份新建表，不改動官方範本或既有活動。
3. 自動驗證匯入、兩組作答、原位寫回、純文字答案、格式保留、無人作答、重複寫回，以及來源移動後拒絕寫回。
4. 結果位於 `output/live-sheets/report.json`，測試表連結位於 `output/live-sheets/test-workbook.txt`。測試表保留供人工查看，可自行刪除。

這項測試會實際讀寫 Google，與前面的離線自動測試不同。授權最多等待 10 分鐘；每次執行需要重新授權，權杖只存於記憶體，結束後清除。測試表不會自動公開分享。

## 常見問題

- **無法開啟網頁**：確認啟動視窗仍開著，且已輸入教師密碼。
- **連接埠已被使用**：改用 `python app.py --port 8001`，瀏覽器開啟 http://127.0.0.1:8001 。
- **Google 顯示尚未設定**：確認檔案位置及名稱正確，沒有多加成 `.json.json`，且用戶端類型為電腦版應用程式。
- **Google 權限不足**：確認登入帳號已加入測試使用者、Sheets API 已啟用，且帳號有該副本的編輯權限。
- **其他電腦或手機無法連線**：目前僅供本機多分頁使用，請在啟動程式的同一台電腦操作。
