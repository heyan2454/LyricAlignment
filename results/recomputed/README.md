# Recomputed Metrics

metric 修正产物：从逐字符 reference/prediction 重算的 `metrics.corrected.json`，
作为 canonical 结果，禁止被原始 aggregate JSON 静默覆盖。

每个子目录对应一次 metric schema 重算；`MANIFEST.json` 记录重算来源与 schema。
