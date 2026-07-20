# Qwen Forced Aligner Raw Smoke

**Updated:** 2026-07-20  
**Metric:** none  
**Current status:** one legacy M4Singer short smoke reported successful; schema-v2 rerun pending

## Model

- model ID: `Qwen/Qwen3-ForcedAligner-0.6B-hf`
- resolved revision: `c07281df297b9905d24a508279258cccf987a064`
- historical local cache: `/home/hyan/Data/lyricalign/models/hf_cache/models--Qwen--Qwen3-ForcedAligner-0.6B-hf/snapshots/c07281df297b9905d24a508279258cccf987a064`
- recorded environment: Python 3.12.3, PyTorch 2.8.0+cu128, Transformers 5.15.0.dev0, RTX 4080 SUPER 32 GB
- unresolved reproducibility item: the Transformers source commit was not captured in the legacy run

## Legacy result

| Sample | Dataset | Duration | Text | Reported result | Evidence strength |
|---|---|---:|---|---|---|
| `m4singer_alto_1_newboy_0000` | M4Singer | 5.005 s | 好的是的我看见到处是阳光 | 12 returned items; no reported structural warnings; undivided wall time 6.253 s | report-level only; original JSON hash and command absent |

The lightweight legacy index is stored at:

`runs/smoke/20260719_m4singer_short_legacy/run_summary.json`

The 6.253 s value must be interpreted as a legacy undivided wall time. Because the old adapter loaded the model lazily inside the first `align()` call, it may include model/processor loading, device transfer, audio decode, forward and timestamp decode. It is not a formal warm-inference runtime or RTF.

## Schema-v2 behavior now implemented

Future runs record:

- model ID, requested revision and resolved revision in every sample output;
- audio SHA256, text SHA256 and behavior-config hash;
- exact skip reason and revision-aware resume behavior;
- model load, audio decode, input preparation, synchronized forward and alignment decode times;
- separate start-order, end-order, negative-duration, overlap, gap and range diagnostics;
- lightweight run summary, command and environment snapshot in `runs/smoke/<run_id>/`;
- external full-output path and SHA256 without storing large outputs in Git.

## Allowed observations

- inference success or failure;
- output empty or non-empty;
- token/segment structure;
- finite timestamps and true ordering violations;
- overlap/gap counts as diagnostic signals;
- visible truncation or late-sequence degradation;
- clearly defined cold/warm runtime fields and exceptions.

## Forbidden conclusions

- alignment accuracy from raw smoke alone;
- GT onset/offset error, Precision/Recall/F1;
- formal RTF from the legacy 6.253 s value;
- threshold tuning or data filtering based only on no-GT outputs.

Official-example smoke and a schema-v2 M4Singer rerun remain pending on the server.
