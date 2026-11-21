# Proposal

## Why

老師在帶領搶答時也需要看到學生正在看的本場名次。同場各組希望能在作答頁直接以小組名討論題目，並在活動結束時清除這段討論。

## What Changes

- 教師的活動頁顯示與學生相同的本場前五名。
- 學生在答題頁左下角開啟同場共用頻道，發言署名使用登入的小組。
- 整場結束時清除訊息，逐題模式的題間仍可聊天。

## Capabilities

### New Capabilities

- `activity-chat` 定義同場討論的參與者、訊息署名與資料生命週期。

### Modified Capabilities

- `classroom-scoring` 讓教師也能查看本場前五組。

## Impact

涉及課堂快照、活動 API、SQLite 暫存訊息、師生頁面與測試。
