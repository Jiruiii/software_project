# 專案工作流程

後續開發一律採用 OpenSpec，這是使用者指定的專案流程。

- 新功能、錯誤修復及行為變更，先建立或更新對應的 OpenSpec change，確認 proposal、specs、design 與 tasks 足以指導實作，再修改程式。
- 依任務套用對應的 OpenSpec skill；既有變更延續使用原 change，避免重複建立。
- 實作時同步維護任務狀態；以實際測試及驗收證據記錄結果，未驗證項目不得標示通過。
- 實作完成後執行 OpenSpec verify 與適當測試；確認所有必要驗收完成後，再同步主規格並歸檔。
- 討論、進度整理及唯讀調查不必另建 change；若結論影響需求或設計，先更新相關 artifacts 再實作。
- 文件使用繁體中文，保留 OpenSpec 結構標題及 SHALL/MUST 關鍵字的英文。
