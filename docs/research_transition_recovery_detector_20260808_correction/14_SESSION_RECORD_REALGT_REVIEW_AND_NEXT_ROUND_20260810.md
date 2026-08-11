# 14. Session Record — Real-GT Discovery, Second Supplement Review, and Next-Round Decisions

**Conversation date:** 2026-08-09 to 2026-08-10 (Asia/Singapore)  
**Scope:** review of Transition–Recovery–Detector work, first and second supplements, discovery/correction of the GT problem, and decisions for the next experiment round.  
**Purpose:** preserve the full reasoning trail, especially the user's questions, objections, and decisions, so later agents do not silently revert to superseded conclusions.

---

## 1. Starting point: review of Transition–Recovery–Detector results

The conversation began with a request to review the current work directory and evidence pack and state the experimental results.

The initial review found that the corrected Transition experiment was more credible than the previous round, but several reporting and aggregation defects remained:

- Transition `TRANSITION_REPORT_v2.json` selected T2 as product candidate and full-song as mechanism candidate, while Markdown displayed `product=None, mechanism=None`; this was traced to inconsistent field names.
- T1/T2 had `wrong_committed_250ms=0` while the same artifacts contained thousands of Unsafe committed units. The serial reaggregator had dropped row-level data, so candidate-derived fields were inconsistent.
- `INTERVAL_METRICS.json` was consumed by reports but had no canonical production script in the archive.
- Closed-loop recovery artifacts showed retry execution but no convincing explanation of where recovery failed.

At that stage, using the then-assumed GT, the apparent result was roughly:

- T2 250-ms target coverage about 40%; T1 very close;
- serial better than full-song under that metric;
- T3 low coverage;
- R/raw evidence was the most useful detector signal but only moderately separable;
- recovery showed almost no useful writeback.

The user explicitly challenged the apparent conflict between the low numeric accuracy and prior Test Demo observations in earlier conversations. The discussion initially considered tolerance (250 ms vs 500 ms / 1 s) and raw-vs-official timing as possible explanations.

---

## 2. First supplemental plan: correction plus full signal completion

The user asked what small-scale experiments/report corrections should be added. The proposed minimal correction set was:

1. repair Transition aggregation and candidate reporting;
2. rebuild reproducible interval metrics;
3. decompose recovery failure into retry failure vs detector blocking vs writeback policy;
4. compare raw and official timing on identical data;
5. run a minimal detector signal ablation.

The user then made an important decision:

> H, P, PR and the other planned signals should be completed now rather than postponed again, because they had repeatedly remained unimplemented.

The user further clarified:

> the signal capabilities are already supported; the issue is that they were not implemented.

This corrected the planning assumption. `blocked_api`, `not_executed`, or zero-coverage were therefore explicitly disallowed as acceptable completion states for H/P/PR unless an actual runtime failure could be demonstrated.

A supplemental plan was created requiring:

- real H extraction;
- coherent second-path P;
- PR propagation-risk target and model;
- R/O/RO/V/P/S/H coverage and ablations;
- one lightweight sequence model;
- interval metrics;
- closed-loop recovery decomposition.

---

## 3. Review of the first supplemental execution

After the first supplement was executed, the user asked for another review.

The review found meaningful progress but also several important defects.

### 3.1 Detector committed-observation mismatch

The same T2 model-selection set had different Safe/Grey/Unsafe distributions between the authoritative Transition artifact and Detector v3. Code review found that the detector could identify which request actually committed a canonical unit, but later R/O row lookup used a dictionary keyed only by canonical id. A later overlap observation could therefore replace the actually committed observation.

This implied that:

- R/O could come from a later overlapping request;
- labels could follow that later row;
- H/P could still use the committed request;
- signal families could therefore be misaligned with each other.

The conclusion was that Detector v3 AUC values could not yet be treated as final.

### 3.2 H had been implemented, but coverage was not what the report claimed

H was no longer a placeholder and real hidden arrays existed. However, unit-level coverage was much lower than request-level artifact coverage because of an assumed timestamp-slot mapping. The report's “100% coverage” was therefore misleading.

### 3.3 P had not yet demonstrated the intended scientific signal

Although P artifacts existed, most requests had `insufficient_paths`, and successful requests often had no genuinely distinct second path. The classifier mainly consumed local top-2 gap and a path-success flag. The review therefore rejected the statement “P is implemented and negative” because the intended coherent competing path had not actually been tested.

### 3.4 Interval metrics still had a correctness bug

Grey and Unsafe were mixed in the unsafe denominator, and song boundaries were not sufficiently protected during intervalization.

### 3.5 PR was executed but the most prominent pooled metric was in-sample

The reported pooled PR AUC was based on fit-and-evaluate on the same episode set. The more meaningful cross-song result was much weaker. PR was therefore considered preliminary/negative rather than a successful predictive signal.

### 3.6 Recovery report conflicted with the underlying decomposition

The underlying data already contained a few retry-improved and accepted/writeback cases, while the summary still said zero writeback. In addition, the code present in the archive could not obviously regenerate the exact decomposition artifact.

This review motivated a **second supplement / final correction pass** rather than a new research branch.

---

## 4. Discussion of next steps from the current route and the larger LyricAlignment view

Before asking for the second supplement implementation plan, the user asked for two levels of forward planning:

> what to do next along the current experiment route, and what to do from the larger LyricAlignment research perspective.

The discussion proposed that the current route should first close correctness defects, then shift from generic detector feature expansion toward understanding **why alignment fails**, how failures propagate, and how recovery should depend on failure type. Suggested near-term ideas included:

- an objective alignment failure taxonomy (local shift, occurrence jump, head/startup error, compression, query dosage, etc.);
- detector output that describes unsafe sub-intervals/failure types rather than only a scalar Safe/Unsafe label;
- targeted recovery interventions rather than repeating the same request;
- treating propagation as a mechanism to analyze before trying to learn a generic PR classifier;
- revisiting slot/sparse-query serial alignment as a potentially simpler robustness mechanism.

At the larger project level, the proposed framing was **Robust Long-form Streaming Lyric Alignment** rather than merely “forced alignment plus engineering guards.” Candidate larger research axes discussed were:

1. imperfect/illegal transcript robustness;
2. uncertainty-aware forced alignment;
3. error propagation in serial alignment;
4. adaptive context/window requirements;
5. slot/sparse-query formulations;
6. active self-verification by perturbing context/query and checking consistency.

The key methodological principle from this discussion was that the project should not keep adding modules merely because they are available. A future paper should ideally retain only a few mechanisms that are empirically necessary and explain both where they succeed and where they fail.

The user then chose **not** to start that larger new research stage immediately. Instead, the user requested a second supplement first so the current evidence could be corrected and frozen.

---

## 5. Second supplemental plan

The user asked for the second supplemental plan to be prepared for Codex review and then OpenCode implementation.

The second plan focused on:

- exact committed-view binding;
- H slot mapping and equivalence audit;
- a truly distinct coherent P second path;
- O/RO schema honesty;
- corrected Grey/Unsafe and song-bounded interval metrics;
- minimal Detector v4 rerun;
- fair normalization for the sequence model;
- source-song-disjoint PR evaluation;
- reproducible recovery before/after/writeback state audit.

The intent was explicitly to **freeze the current stage after correction**, rather than continue a third round of signal expansion.

---

## 6. Review of the second supplement and exploratory work

The user returned with the second supplement plus additional exploratory evidence and asked to continue review and analysis.

During this review, a much more important problem was discovered: **the long-timeline evaluation GT used in previous Transition/Detector/Recovery work was not the real character timing GT.**

### 5.1 Critical GT discovery

`LONG_TIMELINE_MANIFEST` had used a synthetic segment-uniform character timeline. Characters were evenly distributed across a segment. This axis is useful for construction/planning, but it is not the real sung character timing annotation and should not have been used for fine-grained 100/250-ms correctness labels.

The repository also contained the newer 2026-07-23 M4Singer pinyin/slur overlay with much better rule-validated coverage. After applying each segment's global offset, this overlay supplied real character timing for the large majority of the relevant units.

This discovery changed the interpretation of the entire stage.

### 5.2 Real-GT result on the 9-song T2 model-selection subset

The corrected T2 model-selection set contained:

- total canonical units: 3374;
- units with valid real GT: 3228;
- unlabeled by real GT: 146;
- Safe <=100 ms: 3093;
- Grey 100–250 ms: 97;
- Unsafe >250 ms: 38.

Using the **labeled denominator 3228**:

- <=100 ms: about 95.8%;
- <=250 ms: about 98.8%;
- >250 ms: about 1.2%.

This directly invalidated the earlier interpretation that normal serial alignment had only about 40% 250-ms correctness.

### 5.3 Larger exploratory real-GT evaluation

An exploratory all-song artifact reported roughly 60 songs and 20k+ labeled units, with aggregate <=250-ms correctness around 95% and most songs above 90–95%. However, a few songs were catastrophic outliers with very low accuracy.

The review treated this as a strong exploratory result but not yet publication-grade because the exact data/provenance and model-training source-song overlap still need a formal audit.

### 5.4 The research problem therefore changed

The prior story was approximately:

> normal long-form serial alignment is frequently wrong -> detector must reject many ordinary errors -> recovery must rescue them.

The real-GT evidence instead suggested:

> normal alignment is usually very accurate -> a small number of songs/windows fail catastrophically -> the key problem is detecting and safely recovering rare collapse without damaging correct output.

This was judged to be a much better problem formulation.

---

## 7. Detector interpretation after real GT

With real-GT labels, R/raw became much stronger. The second-supplement report contained a high pooled AUROC for R, while H/O/RO/V/P/S did not show a useful incremental gain over R.

The user then made a clear research decision:

> “我觉得raw已经能给出足够的信号了，接下来就是分析在面对偏差极大的极少错误时，这个指标会不会其实不能正确反映。进行分解。其他的信号种类暂时可以不用考虑。”

This decision supersedes further H/P/V/S feature expansion for the next round.

The next detector question is no longer “can we improve global AUC?” It is:

> **Does Raw remain reliable on the rare, very large alignment errors that matter most?**

In particular, the user wants decomposition of high-magnitude errors and investigation of whether the model can be very confidently wrong on occurrence-level or catastrophic failures.

---

## 8. Recovery decision after the GT correction

The user explicitly decided not to abandon recovery:

> “recovery可能还是需要的，先不要放弃，考虑到我们已经发现了gt的重大使用错误，纠正流程后继续。”

This is important because previous retry/recovery success/failure percentages may have been evaluated against the wrong GT and/or triggered on windows that were actually correct under real GT.

The revised recovery logic should therefore be:

1. first evaluate recovery capability on **real-GT-confirmed error windows** (oracle trigger used only for experiment selection/evaluation, not as a model input);
2. separate retry/re-alignment capability from detector triggering;
3. then reconnect the frozen Raw detector and measure full detector-triggered recovery;
4. explicitly measure harm on clean windows and harmful writeback.

The user rejected the implication that recovery should be dropped merely because the old loop looked poor.

---

## 9. User question: which earlier experiments may have been contaminated by the wrong GT?

The user asked:

> “我们之前的实验中，还有什么有很大的风险，可能因为错误使用gt而改变了并对后续造成很大影响？”

The discussion identified high-risk groups:

- Transition T1/T2/T3/full-song selection and 100/250/500/1000-ms metrics;
- all correctness-detector labels/thresholds/interval metrics trained from the synthetic-uniform timeline;
- recovery success rates and oracle-recovery comparisons if improvement was judged using the same wrong timing GT;
- propagation/PR labels if their episode categories depended on timing correctness rather than purely injected state corruption;
- slot/non-slot or serial strategy conclusions whenever the metric used the synthetic timeline;
- invalid-input and mutation conclusions wherever “degradation” meant timing error against the wrong GT.

Lower-risk groups include:

- original Qwen FA LoRA validation if it used the original M4Singer annotation directly;
- pure runtime/model-forward/decoder structural observations;
- mutation construction identities themselves;
- structural cursor/head/query pollution counts that do not use GT (although claimed accuracy benefit still requires real-GT validation).

Because the exact provenance varies by experiment, the next plan must **not guess**. Codex must audit each historical result and classify it.

---

## 10. User question: can the data be expanded?

The user asked:

> “我们的实验数据还可以继续扩张吗？我感觉当前数据集应该是可以支持的？如果你无法得出结论，可以交由codex确认。”

Current evidence strongly suggests that the present 9-song and exploratory ~60-song subsets are not the full limit of M4Singer-derived material. However, the safe maximum cannot be declared from the conversation alone because the following must be checked in the repository and data roots:

- how many source songs have usable 2026-07-23 real-GT overlays;
- how many can be materialized into the long-form/serial format without losing GT mapping;
- which songs belong to the R2 training/validation/test source-song split;
- whether any of the exploratory 60 songs overlap R2 fine-tuning songs;
- how much existing forward/cache coverage can be reused;
- whether source-song-disjoint held-out expansion is possible without leakage;
- whether synthetic-long concatenation introduces seams that should be stratified separately from natural songs.

Therefore the decision is:

> **Do not hard-code 9 or 60 songs. Codex must perform a data-capacity/split audit and then choose the largest safe real-GT evaluation cohort, with a held-out source-song-disjoint core and optional development expansion.**

---

## 11. Final user instruction for this patch

The user requested that this conversation be archived with:

- a complete session record;
- current experimental conclusions;
- a GT-contamination inventory with Codex verification for uncertain items;
- next-round experimental design including reasons, design, purpose, expected results, and what each result would support;
- a new session folder **for the next execution round**, but **not created by this patch**.

The user corrected the initial patch interpretation explicitly:

> “这些内容应该都不是用新的session文件夹，而是要求下一轮使用新的session文件夹工作。下一轮实验设计可以复制一份到新session文件夹。”

Therefore this patch:

- updates documentation in the current archived work directory;
- does **not** pre-create a run/session output directory;
- requires the next execution to create a fresh session/OUT_ROOT;
- requires the next-round plan and Codex-reviewed implementation plan to be copied into that new session before experimental execution.

---

## 12. Current user decisions to carry forward

1. **Raw is the only detector signal family that needs to be actively studied in the next round.** H/P/V/S/O/RO are not next-round priorities unless an audit reveals a blocking dependency.
2. **The key Raw question is catastrophic false confidence**, not another small pooled-AUC gain.
3. **Recovery remains a mainline research question** and must be reevaluated under real GT rather than abandoned based on contaminated results.
4. **Historical GT contamination must be systematically audited.** Uncertain cases are for Codex to resolve from provenance rather than guessed in advance.
5. **Data should be expanded if the dataset/split provenance safely supports it.** The maximum safe cohort is to be computed, not hard-coded.
6. **The next execution must use a new session folder.** This patch itself only documents and plans that future session.
7. **Avoid Cartesian experiment growth.** Prefer a small number of mechanistically distinct recovery interventions and magnitude-stratified Raw analyses.
8. **Use real labeled denominators explicitly.** Unlabeled units must never be silently counted as Safe/Grey/Unsafe.

