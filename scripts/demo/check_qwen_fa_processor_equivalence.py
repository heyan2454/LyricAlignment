#!/usr/bin/env python3
"""Audit official Qwen FA transcript preparation against project pretokenization.

This is an integration diagnostic, not a unit test.  It should be run in the
actual Qwen environment for Chinese, English, and Japanese short samples before
cross-language conclusions are attributed to model quality.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lyricalign.demo.karaoke import normalize_alignment_language, parse_lyrics_text
from lyricalign.training.qwen_fa_runtime import decode_audio, move_inputs


def load_serial() -> Any:
    path = ROOT / "scripts" / "demo" / "align_qwen_fa_serial_demo.py"
    spec = importlib.util.spec_from_file_location("qwen_fa_serial_for_processor_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SERIAL = load_serial()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def tensor_hash(value: Any) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(array.tobytes()).hexdigest()


def input_summary(inputs: Any, timestamp_token_id: int) -> dict[str, Any]:
    ids = inputs["input_ids"][0]
    positions = (ids == timestamp_token_id).nonzero(as_tuple=False).flatten().tolist()
    return {
        "input_ids_length": int(ids.numel()),
        "input_ids_sha256": tensor_hash(ids),
        "timestamp_slot_count": len(positions),
        "timestamp_positions": positions,
        "keys": sorted(inputs.keys()),
    }


def first_mismatch(left: Any, right: Any) -> int | None:
    a = left["input_ids"][0].detach().cpu().tolist()
    b = right["input_ids"][0].detach().cpu().tolist()
    for index, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return index
    return min(len(a), len(b)) if len(a) != len(b) else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--lyrics", type=Path, required=True)
    parser.add_argument("--language", type=normalize_alignment_language, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=os.environ.get("MODEL_ID", "Qwen/Qwen3-ForcedAligner-0.6B-hf"))
    parser.add_argument("--revision", default=os.environ.get("MODEL_REVISION", "c07281df297b9905d24a508279258cccf987a064"))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-files-only", action="store_true", default=os.environ.get("HF_HUB_OFFLINE") == "1")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--run-model", action="store_true")
    args = parser.parse_args()

    import torch
    from transformers import AutoConfig, AutoModelForTokenClassification, AutoProcessor

    kwargs: dict[str, Any] = {"revision": args.revision, "local_files_only": args.local_files_only}
    if args.cache_dir:
        kwargs["cache_dir"] = str(args.cache_dir)
    processor = AutoProcessor.from_pretrained(args.model, **kwargs)
    config = AutoConfig.from_pretrained(args.model, **kwargs)
    audio = decode_audio(args.audio)
    lyrics_text = args.lyrics.read_text(encoding="utf-8-sig")
    document = parse_lyrics_text(lyrics_text, language=args.language)
    units = [item.text for item in document.characters]

    official_inputs, official_words = processor.prepare_forced_aligner_inputs(
        audio=[audio], transcript=[lyrics_text], language=args.language
    )
    project_inputs, project_words = SERIAL.prepare_pretokenized_aligner_inputs(
        processor, audio=audio, alignment_units=units
    )

    timestamp_token_id = int(config.timestamp_token_id)
    payload: dict[str, Any] = {
        "schema_version": "qwen_fa_processor_equivalence_v1",
        "model": args.model,
        "revision": args.revision,
        "language": args.language,
        "project_unit_mode": document.unit_mode,
        "visible_lyrics": lyrics_text,
        "project_units": units,
        "official_words": official_words[0],
        "project_words": project_words[0],
        "unit_lists_equal": list(official_words[0]) == list(project_words[0]),
        "official": input_summary(official_inputs, timestamp_token_id),
        "project": input_summary(project_inputs, timestamp_token_id),
        "input_ids_equal": bool(torch.equal(official_inputs["input_ids"], project_inputs["input_ids"])),
        "first_input_id_mismatch": first_mismatch(official_inputs, project_inputs),
    }

    if args.run_model:
        model = AutoModelForTokenClassification.from_pretrained(
            args.model, revision=args.revision, local_files_only=args.local_files_only,
            cache_dir=str(args.cache_dir) if args.cache_dir else None, dtype=torch.bfloat16,
        ).to(args.device).eval()
        decoded: dict[str, Any] = {}
        for name, inputs, words in (
            ("official", official_inputs, official_words),
            ("project", project_inputs, project_words),
        ):
            batch = move_inputs(inputs, args.device, torch.bfloat16)
            with torch.inference_mode():
                output = model(**batch)
            decoded[name] = processor.decode_forced_alignment(
                output.logits, batch["input_ids"], words, model.config.timestamp_token_id
            )[0]
        payload["decoded"] = decoded
        payload["decoded_equal"] = decoded["official"] == decoded["project"]

    atomic_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
