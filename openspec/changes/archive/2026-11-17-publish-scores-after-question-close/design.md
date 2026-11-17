# Design

## Context
submit 與學生 snapshot 共用 _own_answer，但目前直接回傳資料庫 verdict；_own_score 直接計入尚開放的自動判定分數。

## Goals / Non-Goals
從伺服器回應阻止提前公布正誤與加減分，不只隱藏畫面。不延後內部自動判定，也不更動教師批改或排序。

## Decisions
- _own_answer 接受活動狀態，學生路徑依 _reviewable 判斷該題是否已關閉，未關閉一律回傳 withheld；原資料庫 verdict 不改動。
- 學生總分由已遮蔽的本組答案推導，withheld 單位不計分，另回傳 awaiting_close_units；pending_units 僅計已公布且尚需批改單位。
- 提交、重送、題組逐筆回應與 snapshot 一致遮蔽，結果階段與教師資料保持真實判定。使用既有伺服器倒數 tick 更新公布狀態。

## Risks / Trade-offs
全題模式沒有逐題關閉按鈕 → 等整場結束才公布。簡答關題後仍須教師批改；「待公布」與「未判定」文案清楚區分。

## Migration Plan
不變更資料庫；重啟新版本後，既有活動依當下關題狀態套用公布規則。
