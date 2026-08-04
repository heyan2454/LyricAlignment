# AUTO_FINDINGS_SUMMARY

- status: formal (approved)
- Timeline: 201.078s (ge180=True)
- Slot topology: full+strided (non-contiguous=True)
- unit_recall=0.0, correct_unit_fpr=0.0, gap_recall=1.0
- Assessor operating points: {'high_recall_95': 0.1727820246703941, 'high_recall_99': 0.1547679996332282}

> 自动。draft=False; reasons=[]。正式结论需 sha-matched frozen manifest；否则仅作 draft。

## Baseline quality

- Source: out/formal_run_copy/BASELINE_QUALITY_ANALYSIS.json
- row_coverage=0.534463, start MAE median=0.2723s,
  unsafe_rate>250ms=0.6664
- GT axis ratio M4/MIR=5.17x; seam near=0.6612,
  far=0.6739; feature AUC top=0.5779; self_check=True
- Finding: GT axis sensitivity: 66.6% (M4 synthetic) vs 12.9% (MIR weak) = 5.17x; boundary start MAE median 0.272s; seam near/far unsafe 66.1%/67.4% (seam has no measurable effect); feature AUC top 0.578 (raw_end_entropy) ~0.5, no discriminative power; self_check=True; unit_recall=0 is structural (deleted units have no rows), not decoder failure
