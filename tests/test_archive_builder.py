from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("archive_builder", ROOT / "scripts" / "environment" / "build_archive.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_verify_rejects_missing_required_modules(tmp_path: Path) -> None:
    import zipfile
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("LyricAlignment/ARCHIVE_MANIFEST.generated.json", '{"archive_root":"LyricAlignment","entries":[]}')
    try:
        MODULE.verify(archive)
    except ValueError as exc:
        assert "missing required" in str(exc)
    else:
        raise AssertionError("missing modules must fail archive validation")
