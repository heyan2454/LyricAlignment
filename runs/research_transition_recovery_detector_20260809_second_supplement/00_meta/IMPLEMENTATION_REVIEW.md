{
  "schema_version": "second_supplement_meta_v1",
  "date": "2026-08-09",
  "session_root": "runs/research_transition_recovery_detector_20260809_second_supplement",
  "baseline_readonly": [
    "runs/research_transition_recovery_detector_20260808_corrected",
    "runs/research_transition_recovery_detector_20260809_signal_completion"
  ],
  "external_evidence": "/root/autodl-tmp/lyricalign_sessions/20260809_signal_completion",
  "plan_refs": [
    "/home/hyan/LYRICALIGN_SECOND_SUPPLEMENT_PLAN_20260809.md",
    "/home/hyan/LYRICALIGN_SECOND_SUPPLEMENT_IMPLEMENTATION_PLAN_20260809.md"
  ],
  "audit_findings": {
    "committed_view_mixing": {
      "severity": "P0",
      "confirmed": true,
      "evidence": "newboy 443 committed units, 82 (18.5%) label/feature from non-committed observation (start diff 2.5-3s); rows_to_rowobjs uses {cid:row} last-observation, row_req tracks committed request"
    },
    "H_slot_2i_assumption": {
      "severity": "P0-disputed",
      "confirmed": "partial",
      "note": "infer_slice uses start_slot=2*local_index with slots==2*units assertion; mapping is contract-guaranteed but cache does not persist slot indices"
    },
    "P_insufficient_paths": {
      "severity": "P0",
      "confirmed": true,
      "evidence": "model_selection 36 requests（新算法重算）: 32 ok（distinct second path）/ 4 no_monotone_path; 旧 beam 版本 32 insufficient / 4 ok; 已重写为 exact k-best DP"
    },
    "interval_grey_in_unsafe": {
      "severity": "P0",
      "confirmed": true,
      "evidence": "evaluate_interval_metrics_v2.py:64 l in (1,2)"
    },
    "interval_cross_song": {
      "severity": "P0",
      "confirmed": true,
      "evidence": "build_intervals merges by enumerate index without song grouping"
    },
    "official_end_dropped": {
      "severity": "P1",
      "confirmed": true,
      "note": "align_qwen_fa_serial_demo.py:421 generates official end but runner.py:408 drops it; serial_infer cache rows DO contain official_fixed_global_end_sec -> recoverable without re-forward"
    },
    "recovery_provenance": {
      "severity": "P0",
      "confirmed": true,
      "note": "run_recovery_decomposition.py produces state-level version only; authoritative 36-row before/after decomposition not reproducible from it"
    },
    "report_0_writeback_leftover": {
      "severity": "P0",
      "confirmed": true,
      "note": "13_SUPPLEMENTAL_RESULTS.md still says '0 writeback / 5 all blocked' but decomposition shows 3 writeback commits [4],[1],[3], 3 accept + 2 block"
    }
  }
}
