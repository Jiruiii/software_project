# Proposal

## Why

使用者希望教師密碼不限制長度，目前啟動入口要求至少八字元，登入服務本身沒有此限制。

## What Changes

移除啟動時八字元門檻，允許單字元密碼；保留非空密碼與既有登入驗證，更新啟動說明。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `classroom-access`：教師可設定任意長度的非空密碼。

## Impact

啟動入口、README 與規格；不改資料庫、權限或現有密碼比對方式。
