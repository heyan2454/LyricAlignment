# Patch README — 2026-08-14 Realign Recovery + Visualization Overnight

Base reviewed archive:

```text
LyricAlignment_202608132319_after_unit_realign_overnight_p1p13.zip
```

Evidence reviewed:

```text
unit_realign_evidence_2m_20260813.tar.gz
```

## Purpose

This is a documentation/session activation patch. It does **not** claim the next experiments or visualization adapter are already implemented.

It adds a new session:

```text
docs/sessions/20260814_realign_recovery_visualization_overnight/
```

and updates the active session pointers in:

```text
AGENTS.md
AI_SESSION_ENTRY.md
docs/sessions/SESSION_INDEX.md
```

## Apply

From the repository parent directory, overlay this archive onto the current working tree after inspecting local changes. Example:

```bash
cd /home/hyan/LyricAlignment
unzip -o /path/to/LyricAlignment_patch_20260814_realign_recovery_visualization_overnight.zip -d .
```

The archive paths are relative to the repository root. If `AGENTS.md`, `AI_SESSION_ENTRY.md`, or `SESSION_INDEX.md` have changed since the reviewed 2026-08-13 archive, merge those three pointer changes manually rather than blindly overwriting newer work.

## Codex/OpenCode entry

Read:

```text
docs/sessions/20260814_realign_recovery_visualization_overnight/README.md
...
05_CODEX_HANDOFF.md
```

Codex should create `07_CODEX_IMPLEMENTATION_PLAN.md`; OpenCode/agent should implement only after that plan is reviewed.

## Important frozen decisions

- B4 vs Current baseline is a standalone two-way system comparison;
- Current realign visualization is a separate four-way ablation: baseline / R-U / R-S / R-U->sparse refinement;
- collection precedes visualization;
- visualization rerender must not repeat model forwards;
- multi-realign, fine split, audio recrop/multi-view and coarse->fine are the next main experiments;
- actual writeback remains disabled;
- GPU target <=10h, hard cap <=12h, then CPU/free exploration continues.
