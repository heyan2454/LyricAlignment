from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lyricalign.training.qwen_fa_model import audio_attention_target_regex


class _Tower:
    layers = [object()] * 24


class _Model:
    def get_submodule(self, name):
        assert name == "model.audio_tower"
        return _Tower()
    def named_modules(self):
        for index in range(24):
            for projection in ("q_proj", "k_proj", "v_proj", "out_proj"):
                yield f"model.audio_tower.layers.{index}.self_attn.{projection}", object()
        yield "model.language_model.layers.0.self_attn.q_proj", object()


def test_lora_targets_only_audio_top_half() -> None:
    pattern, targets = audio_attention_target_regex(_Model(), "top_half")
    assert len(targets) == 48
    assert all("audio_tower.layers." in target for target in targets)
    assert "12|13" in pattern
