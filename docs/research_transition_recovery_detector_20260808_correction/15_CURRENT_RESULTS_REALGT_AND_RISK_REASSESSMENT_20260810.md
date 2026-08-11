# 15. Current Results and Conclusions After Real-GT Correction

**Status date:** 2026-08-10  
**Purpose:** define what can currently be treated as supported, what is provisional, and what has been invalidated/superseded by the real-GT discovery.

---

# 1. Evaluation GT correction is the dominant result of the second supplement

## 1.1 What was wrong

The long-timeline construction had a segment-uniform character timeline. This is suitable as a synthetic planning/reference axis but is not the real sung-character annotation. It was nevertheless used by previous Transition/Detector/Recovery experiments for fine-grained timing correctness.

The newer M4Singer pinyin/slur overlay (`20260723_m4singer_overlay_slur_time_v1` lineage) provides much better rule-validated character timing. Its local segment times must be converted to the long-song/global clock using the corresponding segment offsets.

## 1.2 Corrected T2 model-selection numbers

Known artifact values:

```text
total canonical units = 3374
real-GT labeled units = 3228
unlabeled units        = 146
Safe <=100ms           = 3093
Grey 100-250ms         = 97
Unsafe >250ms          = 38
```

Use the **3228 labeled denominator**:

```text
<=100ms  = 95.8% approximately
<=250ms  = 98.8% approximately
>250ms   = 1.2% approximately
```

Any report that divides 3093/97/38 by all 3374 without separately reporting the 146 unlabeled units is incorrect.

## 1.3 Interpretation

The correct current interpretation is:

> The Qwen forced aligner is usually highly accurate on normal M4Singer-derived real-GT material. The important failure mode is a small number of severe/catastrophic songs/windows, not widespread ordinary misalignment.

This supersedes the earlier “~40% <=250ms serial correctness” story.

---

# 2. Larger exploratory real-GT result

The second-supplement evidence contains `ALL_SONGS_250MS_REALGT.json`, covering roughly 60 songs and >20k labeled units. It reports an aggregate <=250ms accuracy around the mid-90% range, with most songs above 90–95% but a small number of dramatic outliers.

Examples called out during review included songs around:

```text
~5-6% <=250ms
~36% <=250ms
~68% <=250ms
~83% <=250ms
```

while the majority were much higher.

## Strength of conclusion

**Strong exploratory evidence:** normal-case performance is high and error distribution is heavy-tailed across songs.

**Not yet publication-grade:** the exact generation provenance, source-song split, R2 training overlap, and maximal usable cohort must be audited before this is presented as held-out generalization.

---

# 3. Transition conclusions

## 3.1 Old Transition selection is contaminated

The previous T1/T2/T3/full-song comparisons and candidate selection used synthetic-uniform timing correctness. Therefore the following old statements are **not frozen real-GT conclusions**:

- serial > full-song by the previously reported +8 pp scale;
- T1 ~= T2 under the previous 250-ms numbers;
- T2 is the nominal product candidate under the old correctness metric;
- T3 has poor correctness after conditioning on commit coverage.

They may remain true, but they must be **reaggregated with real GT**.

## 3.2 Low-cost next action

The model predictions already exist. Recompute T1/T2/T3/full-song 100/250/500/1000-ms metrics using real GT and explicit labeled/unlabeled denominators before retaining any Transition policy conclusion.

---

# 4. Raw detector conclusion

## 4.1 Current evidence

With real-GT labels, the R/raw feature family became much more separable than under the synthetic-uniform labels. The current report gives a very high pooled unit AUROC for R and does not show useful incremental improvement from H/O/RO/V/P/S combinations.

`light_merge` bug-fixed retrospective A-heldout evaluation (`results/corrected_detector_summary.md`, status `retrospective_after_light_merge_fix`):

```text
raw     protected_recall ≈95.7%  (safe_accept ≈83.2%)
official protected_recall ≈96.3%  (safe_accept ≈73.0%)
```

This is **not a clean formal freeze→untouched-test result**; the higher protected recall is bought at a lower safe-accept rate, and FAMILY_LOO slots are not yet filled.

## 4.2 What can be concluded

Supported direction:

> Raw posterior/geometry is currently sufficient as the sole detector family to carry forward into the next round.

This does **not** yet prove that R is safe for catastrophic failures.

## 4.3 Main unresolved risk

Pooled AUROC can be high even if the detector fails the rare errors that matter most. In particular, an occurrence-level jump can be **confidently wrong**: the posterior may be sharp at the wrong repeated chorus or wrong temporal occurrence.

The next Raw study must therefore focus on:

- >0.5 s, >1 s, >2 s, >5 s, >10 s errors;
- catastrophic contiguous runs;
- catastrophic windows/songs;
- high-confidence catastrophic false negatives;
- leave-one-catastrophic-song-out generalization.

The target is not “raise AUROC 0.97 to 0.98”; it is “measure whether Raw ever becomes falsely confident when the alignment is badly wrong.”

---

# 5. Other detector signal families

H/P/V/S/O/RO are **not next-round priorities**.

Current evidence suggests:

- H contains some correctness information but does not improve R enough to justify further layer search now;
- V and S do not show useful increment over R in the current real-GT run;
- P's k-best path implementation now executes more broadly, but most second paths are very local boundary alternatives rather than clear second-occurrence trajectories;
- O/RO schema is partial/start-side in some artifacts.

These are useful archived negative/preliminary results, but no additional feature-family expansion should be scheduled unless the Raw catastrophic analysis reveals a specific blind spot that motivates a targeted complementary signal.

The negative feature-family results cited from the first/second supplement predate the confirmed `light_merge` postprocess fix and must be treated as **`unresolved_after_bugfix`, not disproved**. Their real-GT status after the fix is unknown and must be re-evaluated before any "feature family X has no benefit" statement is made.

---

# 6. Threshold/interval interpretation

The old R95 implementation used a quantile on a very small number of Unsafe validation units. With a discrete finite sample, interpolation can miss the requested recall target.

For any future R95/SA operating point:

- freeze thresholds using order statistics appropriate to the actual integer count;
- report the achieved integer numerator/denominator;
- separate ACCEPT / UNCERTAIN / REJECT;
- report REJECT-only and protected=(REJECT+UNCERTAIN) separately;
- intervalize separately per source song;
- keep Grey separate from Unsafe.

The key detector metric in the next round should move toward **catastrophic-event/window recall and clean-window harm**, not just aggregate unit R95.

---

# 7. PR conclusion

Current source-song-held-out/out-of-fold PR performance is approximately random-to-weak and does not show a reliable ability to predict future propagation risk from the current feature formulation.

Unless GT-lineage audit shows that the PR target itself was contaminated in a way that invalidates even this negative result, PR is **not a next-round priority**.

If the PR target depends on old correctness labels, Codex must mark the old result for recomputation or retirement. Do not invest in PR model tuning in the next round.

---

# 8. Recovery conclusion after GT correction

The old recovery conclusion is not trustworthy as a capability estimate because:

- some trigger/error definitions were derived from the wrong GT;
- many retry windows did not have a valid real-GT before/after comparison;
- some windows considered “bad” under the old axis are actually good under real GT;
- retry can damage correct alignments and may even write back a worsened result.

The previously reported ~14–16% oracle-recovery range used the synthetic-uniform timeline GT and may also have used GT directly to select retry/query; it therefore serves only as a **historical synthetic-GT oracle diagnostic**, not a real-GT/no-GT recovery upper bound.

Therefore the correct conclusion is **not** “recovery is useless.”

The correct conclusion is:

> Recovery must be reevaluated from scratch on real-GT-confirmed error windows, separating recovery capability from detector triggering and explicitly measuring harm.

The user explicitly chose to keep recovery on the mainline.

---

# 9. Data expansion conclusion

The existing data likely support expansion beyond the current 9-song model-selection subset and the exploratory ~60-song evaluation. However, the safe maximum is unknown until provenance is audited.

Do **not** freeze “60 songs” as a design limit.

Codex must compute:

- all source songs with usable real GT;
- all source songs with serial/full-song predictions already cached;
- R2 fine-tuning train/validation/test source-song identities;
- overlap between candidate evaluation songs and R2 training sources;
- proportion of valid labeled units per song;
- natural vs synthetic-long/seam status;
- whether Test Demo / MIR-1K can be used as OOD or no-GT supporting evidence under a separate metric schema.

Then choose the largest source-song-disjoint evaluation cohort that fits the existing compute budget.

---

# 10. Current research picture

The stage should now be interpreted as:

```text
normal forced alignment is usually accurate
    -> rare severe/catastrophic collapse exists
    -> Raw may already expose abnormality
    -> test whether Raw remains trustworthy in the far error tail
    -> if detected, recovery must repair real errors without damaging clean output
```

This is a substantially cleaner research problem than the earlier “ordinary alignment is broadly poor” framing.

