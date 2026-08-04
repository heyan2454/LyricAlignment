#!/usr/bin/env python3
"""Normalize a blinded human-review CSV without discarding the original notes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ALLOWED = {
    "VALID_STABLE", "VALID_BUT_UNCERTAIN", "TAIL_COLLAPSE", "HEAD_COLLAPSE",
    "WRONG_REPEATED_SECTION", "MULTI_SECTION_SPLIT", "GLOBAL_SHIFT", "LOCAL_SHIFT",
    "ZERO_DURATION_CLUSTER", "UNRESOLVED",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_labels(note: str) -> tuple[list[str], str]:
    explicit = [token.strip() for token in note.split(",") if token.strip() in ALLOWED]
    if explicit:
        return sorted(set(explicit)), "explicit_csv_label"
    labels: set[str] = set()
    if any(token in note for token in ("无法", "不确定", "不符？", "尾部判断失败")):
        labels.add("UNRESOLVED")
    if "全零" in note:
        labels.add("ZERO_DURATION_CLUSTER")
    if "头" in note and "坍缩" in note:
        labels.add("HEAD_COLLAPSE")
    if any(token in note for token in ("尾部", "后面", "后一半", "后续", "最后")) and "坍缩" in note:
        labels.add("TAIL_COLLAPSE")
    if "延长" in note or "拖延" in note or "卡住" in note:
        labels.add("LOCAL_SHIFT")
    if "复制" in note and any(token in note for token in ("乱配", "虚假匹配", "错配")):
        labels.add("WRONG_REPEATED_SECTION")
    if "整段坍缩" in note or "全部坍缩" in note:
        labels.add("ZERO_DURATION_CLUSTER")
    return sorted(labels), "conservative_note_normalization" if labels else "note_preserved_no_label_inferred"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    csv_path = args.csv.resolve()
    packets = json.loads(args.packets.resolve().read_text(encoding="utf-8"))["packets"]
    key = json.loads(args.key.resolve().read_text(encoding="utf-8"))["key"]
    bundle = json.loads(args.bundle.resolve().read_text(encoding="utf-8"))["cases"]
    packet_ids = {str(row["blind_id"]) for row in packets}
    key_by_id = {str(row["blind_id"]): row for row in key}
    case_by_request = {str(row["request_id"]): row for row in bundle}
    global_notes: list[str] = []
    annotations: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="gb18030", newline="") as handle:
        for source_line, row in enumerate(csv.reader(handle), start=1):
            if not row or not any(cell.strip() for cell in row):
                continue
            blind_id = row[0].strip()
            note = ",".join(row[1:]).strip().strip(",").strip()
            if not blind_id.startswith("R-"):
                global_notes.append(",".join(row).strip().strip(",")); continue
            if blind_id not in packet_ids:
                raise ValueError(f"line {source_line}: unknown blind_id {blind_id}")
            labels, provenance = normalized_labels(note)
            annotations.append({"blind_id": blind_id, "source_line": source_line,
                                "raw_note": note, "normalized_labels": labels,
                                "normalization_provenance": provenance,
                                "severe_error_minutes": None, "longest_error_sec": None,
                                "unresolved": "UNRESOLVED" in labels})
    by_id = {row["blind_id"]: row for row in annotations}
    if len(by_id) != len(annotations):
        raise ValueError("duplicate blind_id in human CSV")
    missing = sorted(packet_ids - set(by_id))
    if missing:
        raise ValueError(f"missing human labels for {len(missing)} packets")
    args.out.mkdir(parents=True, exist_ok=True)
    raw_dir = args.out / "raw"
    raw_dir.mkdir(exist_ok=True)
    raw_copy = raw_dir / "人工意见.gb18030.csv"
    shutil.copy2(csv_path, raw_copy)
    blind_payload = {
        "schema": "research_v7/human_blind_annotations_v1", "source_encoding": "gb18030",
        "source_sha256": sha256(csv_path), "packet_sha256": sha256(args.packets.resolve()),
        "global_notes": global_notes, "case_count": len(annotations),
        "annotations": sorted(annotations, key=lambda row: row["blind_id"]),
    }
    blind_path = args.out / "normalized_blind_annotations.json"
    blind_path.write_text(json.dumps(blind_payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    decoded: list[dict[str, Any]] = []
    for annotation in annotations:
        decoded_key = key_by_id[annotation["blind_id"]]
        case = case_by_request[str(decoded_key["request_id"])]
        decoded.append({**annotation, "request_id": decoded_key["request_id"], "item_id": decoded_key["item_id"],
                        "mutation_type": decoded_key["mutation_type"], "evidence_source": case["evidence_source"],
                        "evidence_sha256": case["evidence_sha256"]})
    decoded_path = args.out / "experimenter_decoded_annotations.json"
    decoded_path.write_text(json.dumps({"schema": "research_v7/human_decoded_annotations_v1", "case_count": len(decoded),
                                        "annotations": sorted(decoded, key=lambda row: row["blind_id"])}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    labels = Counter(label for row in annotations for label in row["normalized_labels"])
    by_mutation: dict[str, Counter[str]] = defaultdict(Counter)
    for row in decoded:
        by_mutation[str(row["mutation_type"])].update(row["normalized_labels"] or ["NO_LABEL_INFERRED"])
    summary_path = args.out / "summary.json"
    summary_path.write_text(json.dumps({"schema": "research_v7/human_review_summary_v1", "case_count": len(annotations),
                                         "global_notes": global_notes, "normalized_label_counts": dict(sorted(labels.items())),
                                         "by_mutation": {key: dict(sorted(value.items())) for key, value in sorted(by_mutation.items())},
                                         "unresolved_count": sum(row["unresolved"] for row in annotations)}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rules_path = args.out / "NORMALIZATION_RULES.md"
    rules_path.write_text("""# Human-review normalization\n\nThe original GB18030 CSV is preserved under `raw/` and is authoritative.\n\n- English taxonomy tokens in the CSV are copied exactly.\n- Chinese free text is retained in `raw_note`; machine-readable labels are conservative keyword normalizations with provenance per row.\n- No accuracy, MAE, or duration is inferred from no-GT human comments.\n- `experimenter_decoded_annotations.json` joins the blind labels to the restricted decode key and must not be shared with a blinded reviewer.\n""", encoding="utf-8")
    manifest_path = args.out / "evidence_manifest.json"
    files = [raw_copy, blind_path, decoded_path, summary_path, rules_path]
    manifest_path.write_text(json.dumps({"schema": "research_v7/human_review_evidence_manifest_v1",
                                          "inputs": {str(path): sha256(path.resolve()) for path in (csv_path, args.packets.resolve(), args.key.resolve(), args.bundle.resolve())},
                                          "files": {path.name: sha256(path) for path in files}}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    archive_path = args.out.with_suffix(".tar.gz")
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in [*files, manifest_path]:
            archive.add(path, arcname=f"{args.out.name}/{path.relative_to(args.out)}")
    print(json.dumps({"status": "complete", "case_count": len(annotations), "out": str(args.out),
                      "archive": str(archive_path), "labels": dict(sorted(labels.items()))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
