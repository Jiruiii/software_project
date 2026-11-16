# 多組搶答驗收證據

這些檔案是 2026-11-16 13:11（Asia/Taipei）實際執行 `python tests/run_many_groups.py` 的輸出副本，首次上傳 GitHub 時從本機 `output/playwright/` 挑選保存。沒有重新生成或修改測量結果；原始暫存輸出不全部上傳。

- [中文摘要](many-groups-summary.txt)
- [完整結果](many-groups-report.json)
- [老師結果畫面](many-groups-teacher-results.png)
- [學生手機版結果畫面](many-groups-student-results.png)

HTTP 測試為 30 組、6 題、3 輪，540 筆答案。畫面測試另建立 30 組、180 筆答案，實際開老師及 3 組學生分頁，其他組以程式模擬。畫面測試每題先讓不同指定小組送出，再由其餘 29 組同時作答，用以核對各題不同贏家。

所有組別名稱與答案均為合成測試資料；活動代碼屬於已關閉且已清除的暫時測試服務。未使用真實學生資料、Google 授權或雲端寫回。這是本機測試，不代表 30 台實體裝置的校園網路負載保證。

重新執行會在 `output/playwright/` 產生新的結果；此處保留這次發布時的歷史測試證據，不隨重跑自動覆蓋。
