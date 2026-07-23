from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "training" / "finalize_qwen_fa_r2_manual.sh"


def test_manual_finalizer_is_safe_by_default() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'MODE="${1:-inspect}"' in text
    assert "This entry intentionally does NOT rerun the M4Singer sealed test" in text
    assert 'if [ -e "$FINAL_OOD_DIR" ]' in text
    assert "refusing to overwrite existing final OOD path" in text
    assert "best_checkpoint.json" in text
    assert "evaluation_identity.json" in text


def test_manual_finalizer_uses_frozen_mir1k_identity() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "bd8109d608247b78407c1d63e9f648b83f697a00c5c0b05b3fe93c87b42c884f" in text
    assert "78d7054ada0a3fb5ec3cd916174d094d78ab5d96f67d0112408de30dc24469c9" in text
    assert "--split test" in text
    assert 'usage": "ood_test_only"' in text
