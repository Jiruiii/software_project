## ADDED Requirements

### Requirement: 工作表選擇與確認一致

系統 SHALL 自動預覽選定的分頁，只允許匯入目前網址與分頁的有效預覽。教師說明 SHALL 反映關題後自動同步，並將本機管理設定收合。

#### Scenario: 預覽回應順序顛倒

- **WHEN** 老師先預覽 A 再切換至 B，A 的回應較晚抵達
- **THEN** 預覽、建立的活動及同步來源皆為 B
