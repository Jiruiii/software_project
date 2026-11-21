# Proposal

## Why

學生在多題搶答中需要一邊答題，一邊看見本場的競爭狀況。目前學生只能查看自己的本場分數，切換到課程排行榜又會混入過去活動的成績。

## What Changes

- 學生作答區旁顯示最多五組的本場排名，隨已公布得分及改判更新。
- 以組名穩定排序同分組別，保留並列名次。準備中與結束後使用原有活動頁面。

## Capabilities

### New Capabilities

### Modified Capabilities

- `classroom-scoring` 定義作答中的本場前五組與公布時機。
- `quiz-session` 釐清逐題保底的資格名單與可公開的本場名次。

## Impact

修改學生活動快照、答題頁側欄及相關測試。沿用既有計分資料與畫面自動更新機制。
