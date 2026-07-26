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


def test_build_excludes_stale_generated_manifest_and_has_unique_members(tmp_path: Path) -> None:
    import subprocess
    import zipfile

    root = tmp_path / "repo"
    required = [
        "src/lyricalign/datasets/m4singer.py",
        "src/lyricalign/datasets/mir1k.py",
        "scripts/datasets/audit_m4singer.py",
    ]
    for relative in required:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test\n", encoding="utf-8")
    (root / MODULE.GENERATED_MANIFEST).write_text('{"stale": true}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)

    original_root = MODULE.ROOT
    MODULE.ROOT = root
    try:
        archive = tmp_path / "good.zip"
        manifest = MODULE.build(archive, "LyricAlignment")
        result = MODULE.verify(archive)
    finally:
        MODULE.ROOT = original_root

    assert all(row["path"] != MODULE.GENERATED_MANIFEST for row in manifest["entries"])
    assert result["status"] == "passed"
    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
    assert len(names) == len(set(names))
    assert names.count(f"LyricAlignment/{MODULE.GENERATED_MANIFEST}") == 1


def test_verify_rejects_duplicate_zip_member_names(tmp_path: Path) -> None:
    import warnings
    import zipfile

    archive = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("LyricAlignment/duplicate.txt", "one")
            handle.writestr("LyricAlignment/duplicate.txt", "two")
    try:
        MODULE.verify(archive)
    except ValueError as exc:
        assert "duplicate member names" in str(exc)
    else:
        raise AssertionError("duplicate ZIP members must fail archive validation")


def test_repository_root_has_no_obsolete_patch_or_archive_copies() -> None:
    forbidden = {
        "APPLY.md",
        "APPLY_SPLEETER_EXPLICIT_WEIGHTS_HOTFIX.md",
        "ARCHIVE_MANIFEST.json",
        "ARCHIVE_METADATA.json",
        "ARCHIVE_REPORT.md",
        "PATCH_APPLY_STRICT_OVERLAP_TRANSCRIPT_V3.md",
        "PATCH_APPLY_STRICT_SERIAL_CORE.md",
        "PATCH_DEMO_SPLEETER_20260726.md",
        "PATCH_MANIFEST.sha256",
        "PATCH_MANIFEST_YESSODA_TAIL_WINDOWED.sha256",
        "PATCH_YESSODA_TAIL_WINDOWED_20260726.md",
        "README_IMMEDIATE_ALL.md",
        "STRICT_OVERLAP_TRANSCRIPT_V3_MANIFEST.sha256",
        "STRICT_SERIAL_CORE_PATCH_MANIFEST.sha256",
    }
    present = sorted(name for name in forbidden if (ROOT / name).exists())
    assert present == []
    assert not (ROOT / "docs" / "archive" / "legacy_root_artifacts_20260726").exists()
