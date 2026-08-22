# 2026-08-16 产品化验证 Milestone 清单

## 数据与 Split
- [x] 新数据集获取与登记
- [x] Evaluation V1 grouped split draft
- [x] leakage audit + manifest SHA
- [ ] split manifest 正式 review/冻结

## 基础设施
- [x] dataset readiness audit
- [x] baseline identity freeze
- [x] vocal derivation plan
- [x] behavior registry
- [x] sealed runner access control (`guarded_run.py`)
- [x] quality check script

## GTSinger 中文
- [x] 75 段 diagnostic 全量 R0/R1/R2
- [x] GT 数值评测（1226 字符）
- [x] hard-case 子清单
- [x] 3 个 silence/window 消融（无变化）
- [x] raw decoder 全量 diagnostic 验证（both_100ms 90.05% -> 91.84%）
- [x] raw decoder 全量 regression_selection 验证（both_100ms=89.49%）
- [x] regression_selection official baseline 同集合对比（official 87.47% vs rawdec 89.49%）
- [ ] R-U/R-S/R-CF 等 recovery 机制消融

## PJS 日语
- [x] MusicXML 歌词提取
- [x] pjs001 smoke
- [x] pjs001-005 batch smoke
- [ ] phoneme-level GT 正式评测

## MIR-MLPop / JamendoLyrics
- [x] raw mixture smoke（MIR 30s）
- [x] operational input manifest
- [ ] vocal-only 派生后正式评测

## Sealed
- [ ] sealed milestone runner 端到端验证
- [ ] sealed 结果报告

## 当前状态
- 已完成产品化验证的大部分基础设施和 GTSinger 中文 first-light。
- 下一步重点：recovery 机制消融、PJS 正式评测、vocal 派生。
