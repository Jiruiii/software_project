# 題型、可選下注與即時分數驗收

日期：2026-11-17（Asia/Taipei；JSON 報告使用 UTC）

變更：`add-question-types-and-optional-stakes`。

## Summary

| 面向 | 結果 |
|---|---|
| Completeness | 4 項任務已實作及驗收；4 個新增／修改需求均有實作 |
| Correctness | 4/4 需求、9/9 情境具備實作及測試證據 |
| Coherence | 沿用現有交易、權限、題組計分、輪詢畫面與寫回方式；無新增外部服務 |

## Requirements and scenarios

| 需求與情境 | 實作 | 驗證 |
|---|---|---|
| E-04 分數與重送、不押與關閉下注 | `quiz_service.py:231`、`quiz_extras.py:73`、`quiz_extras.py:215` | `test_no_bet_default_switch_and_all_groups_autograded`、`test_mixed_bundle_atomicity_manual_review_and_retry`；瀏覽器四種組合 |
| E-10 同分與未判定、本組即時分數 | `quiz_extras.py:79`、`quiz_extras.py:362`、`public/app.js` | 原排行測試及 `test_live_own_score_privacy_regrade_and_activity_isolation`；作答中批改、改判、同步 |
| 題型／下注設定與鎖定、題組設定原子性 | `quiz_extras.py:184`、`app.py:117`、`public/app.js` | `test_configuration_validation_stage_and_secret_filter`、`test_mixed_bundle_atomicity_manual_review_and_retry`；未儲存設定阻止開始 |
| 多組自動判定 | `quiz_extras.py:215`、`quiz_service.py:248` | `test_thirty_groups_choice_scores_and_unique_correct_winner`、`test_http_does_not_accept_client_verdict_or_score`；瀏覽器兩組分別加扣分 |
| 混合題組與重送 | `quiz_extras.py:59`、`quiz_service.py:231` | 混合題組提交、重送不覆蓋人工改判、後一子題無效時整組回滾 |
| 原位寫回 | 現有成功者挑選與 Google 寫回服務 | `test_choice_export_uses_correct_candidate_literal_text`；正確組遞補及以字串寫回 `=1+1` |

## Evidence

- `tests.txt`：完整 63 項測試通過，包含資料庫遷移、權限隔離、各組分數、跨活動歸零及 30 組單選並發。
- `question-types-report.json`：單選＋下注、單選＋不押、簡答＋下注、簡答＋不押；草稿重整保留選項與 0 分、正解不下傳學生、活動內改判同步。
- `extras-report.json`：原 E-01～E-11 瀏覽器回歸全部通過。
- `many-groups-report.json`：30 組 × 6 題 × 3 輪共 540 筆 HTTP 作答；另驗證結束競態、同組衝突及重送。瀏覽器核對教師 180 格與 3 個學生分頁，無畫面錯誤。
- `question-types-teacher-settings.png`、`question-types-student.png`：教師設定及 390 px 學生畫面已目視檢查，無水平溢出。
- `openspec validate --all --strict`：變更及全部正式規格通過；同步後再檢查。

## Assessment

CRITICAL：0；WARNING：0；SUGGESTION：0。規格、設計與可觀察行為一致，無略過的規格核對項目。

驗收範圍為本機隔離環境；多人測試使用模擬請求及實際瀏覽器分頁，並非 30 台實體裝置或公網負載測試。本次新增題型的 Google 寫回以模擬 API 驗證，未重新操作真實 Google 帳號；未更動現有授權或版面定位流程。
