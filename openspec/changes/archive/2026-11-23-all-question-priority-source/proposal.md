# Proposal

## Why

全題模式目前讓所有組別同時送出。老師希望在同一門課的下一場活動，讓先前成績較低的小組獲得三秒先答機會。

## What Changes

- 授課老師可在全題活動準備時選擇同課程已結束的場次，或維持全班同時開始。
- 開場時計算並保存先答資格，學生即時看到本組能否作答。單題與題組均適用。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `quiz-session` 增加全題模式的跨場保底，並釐清逐題保底與全題預設行為。

## Impact

涉及課程場次對應、活動規則、教師設定、學生作答畫面與測試。沿用 SQLite 與現有計分方式。
