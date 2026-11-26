# Proposal

## Why

老師需要在同一場活動內一邊收件一邊批改。手動出題、助教協作及回顧操作也需要和現有的題組計分、課程授權及學習單同步一致。

## What Changes

全題模式可個別關閉搶答單位。手動建題可明確指定子題，備課可預填參考答案。授課老師與助教可改回待判及跨登入復原自己的批次。回放可調速。授課老師可移除助教，現任助教可看該課排行。

## Capabilities

### New Capabilities

### Modified Capabilities

- teacher-workflow 涵蓋依模式與所選題目顯示主持控制。
- quiz-session 涵蓋手動題組及全題關題。
- classroom-review 涵蓋預填參考答案、跨登入批次復原及回放速度。
- classroom-scoring 涵蓋關題公布分數及改回待判。
- course-accounts 涵蓋助教名單、移除及工作階段授權。
- course-leaderboard 涵蓋助教的課程排行。

## Impact

影響活動與帳號 API、SQLite 增量升級、既有課程及活動頁面、背景 Sheets 同步、操作文件及回歸測試。
