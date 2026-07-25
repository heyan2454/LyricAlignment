from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "demo" / "run_yessoda_tail_windowed.sh"
ALIGNER = ROOT / "scripts" / "demo" / "align_qwen_fa_tail_windowed.py"
RENDERER = ROOT / "scripts" / "demo" / "render_qwen_fa_tail_windowed.py"


def test_tail_demo_files_exist_and_python_parses() -> None:
    assert RUNNER.is_file()
    for path in (ALIGNER, RENDERER):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_runner_freezes_requested_timestamps_and_lyrics() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert 'trim_tail 185 "$CASE_0305"' in text
    assert 'trim_tail 192 "$CASE_0312"' in text
    assert "想要毫无心事地睡去" in text
    assert text.count("即便明日将得过且过毫无期许") == 2
    assert text.count("白昼靠近了 街灯褪色 与我远隔") == 2


def test_runner_uses_separate_output_tree_and_windowed_only_entry() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "qwen_fa_tail_windowed_0305_0312" in text
    assert "align_qwen_fa_tail_windowed.py" in text
    assert "render_qwen_fa_tail_windowed.py" in text
    assert "--core-sec \"$CORE_SEC\"" in text
    assert "--left-context-sec \"$LEFT_CONTEXT_SEC\"" in text
    assert "--right-context-sec \"$RIGHT_CONTEXT_SEC\"" in text


def test_alignment_script_has_only_windowed_mode_and_six_outputs() -> None:
    text = ALIGNER.read_text(encoding="utf-8")
    assert '"mode": "windowed"' in text
    assert '("r0", "raw", None)' in text
    assert '("r1", "projector", args.r1_checkpoint)' in text
    assert '("r2", "lora", args.r2_checkpoint)' in text


def test_runner_defaults_to_sixty_second_cores_with_ten_second_audio_context() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert 'CORE_SEC="${CORE_SEC:-60}"' in text
    assert 'LEFT_CONTEXT_SEC="${LEFT_CONTEXT_SEC:-10}"' in text
    assert 'RIGHT_CONTEXT_SEC="${RIGHT_CONTEXT_SEC:-10}"' in text
    assert '--future-character-ratio "$FUTURE_CHARACTER_RATIO"' in text
    assert '--seam-tolerance-sec "$SEAM_TOLERANCE_SEC"' in text
