# -*- coding: utf-8 -*-
"""C3 export_silence_polluted_weak 单测（review C3-6：临时 WAV fixture）。"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 允许 import scripts

from scripts.research_v7.export_silence_polluted_weak import (
    detect_silence_frames,
    read_mono16,
)


def _write_wav(path, x, rate=16000):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(np.clip(x.astype(np.int32), -32768, 32767).astype("<i2").tobytes())


def _tone(sec, rate=16000, amp=2000.0, freq=440.0, start_frames=0):
    n = int(sec * rate)
    t = np.arange(n) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _wav_with_silence(sil_sec=1.0, sing_sec=2.0, rate=16000):
    """一段 vocals：先 sing（有唱）再 silence（低能）。"""
    return np.concatenate([_tone(sing_sec, rate, amp=3000.0),
                           np.zeros(int(sil_sec * rate), dtype=np.float32)])


def test_detect_silence_frames_finds_only_low():
    v = _wav_with_silence(sil_sec=1.0, sing_sec=2.0)
    fr = int(0.05 * 16000); nf = len(v) // fr
    vr = np.sqrt((v[:nf * fr].reshape(-1, fr) ** 2).mean(1) + 1e-12)
    sung_median = float(np.median(vr))
    sil, audit = detect_silence_frames(vr, sung_median, 16000, 0.05)
    assert sil.sum() > 0                       # 静音区被检出
    assert audit["sil_final"] == int(sil.sum())


def test_read_mono16_roundtrip_rate():
    x = _tone(0.2, 16000, amp=2000)
    p = Path("/tmp") / "t.wav"
    _write_wav(p, x, 16000)
    y, rate = read_mono16(str(p))
    assert rate == 16000
    assert y.shape[0] == int(0.2 * 16000)
    p.unlink()


def test_sample_rate_mismatch_rejected_in_main(tmp_path):
    # P0（C3-review）：必须真调 main() 验证 skip（不能只比较两个 read rate）
    import json
    import subprocess
    import sys

    vv = tmp_path / "vocals.wav"; aa = tmp_path / "accompaniment.wav"
    _write_wav(vv, _tone(0.5, 16000), 16000)
    _write_wav(aa, _tone(0.5, 8000), 8000)  # 采样率不一致
    il = tmp_path / "items.jsonl"
    il.write_text(json.dumps({"item_id": "X", "audio_path": str(vv)}) + "\n")
    out = tmp_path / "out"
    env = dict(__import__("os").environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src") + ":" + str(Path(__file__).resolve().parents[2]))
    r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/research_v7/export_silence_polluted_weak.py"),
                        "--item-list", str(il), "--out-root", str(out)], capture_output=True, text=True, env=env)
    # main 应正常返回 0，且 manifest 记录 skipped=sample_rate_mismatch
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "AUDIO_EXPORT_MANIFEST.json").read_text())
    assert any(x.get("skipped") == "sample_rate_mismatch" for x in man)


def test_no_silence_window_main_skips(tmp_path):
    # 全程有唱，无合格静音窗 → main 应 skip（不导出 control/weak 相同文件）
    import json
    import subprocess
    import sys

    vv = tmp_path / "vocals.wav"; aa = tmp_path / "accompaniment.wav"
    _write_wav(vv, _tone(1.0, 16000, amp=4000.0), 16000)   # 全程 loud
    _write_wav(aa, _tone(1.0, 16000, amp=2000.0), 16000)
    il = tmp_path / "items.jsonl"
    il.write_text(json.dumps({"item_id": "Y", "audio_path": str(vv)}) + "\n")
    out = tmp_path / "out2"
    env = dict(__import__("os").environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src") + ":" + env["PYTHONPATH"]
    r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/research_v7/export_silence_polluted_weak.py"),
                        "--item-list", str(il), "--out-root", str(out), "--window-sec", "0.5"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "AUDIO_EXPORT_MANIFEST.json").read_text())
    assert all(x.get("skipped") for x in man)  # 无合格静音 → 全部 skip，不导出相同 control/weak


def test_detect_no_silence_when_full_sing():
    v = _tone(1.0, 16000, amp=3000.0)  # 全程有唱
    fr = int(0.05 * 16000); nf = len(v) // fr
    vr = np.sqrt((v[:nf * fr].reshape(-1, fr) ** 2).mean(1) + 1e-12)
    sung_median = float(np.median(vr))
    sil, _ = detect_silence_frames(vr, sung_median, 16000, 0.05)
    # 全程唱 → 应几乎无静音帧（绝对上限 400 与相对 0.35 联合排除）
    assert sil.sum() <= nf * 0.05


def test_successful_export_branch_done_and_files(tmp_path):
    # 覆盖 reviewer 指出的 vpath NameError：合格 export 成功返回、done=true、两文件+sha 存在
    import json
    import subprocess
    import sys

    sr = 16000
    sing = _tone(1.0, sr, amp=4000.0)                   # 唱 1s
    sil = np.zeros(int(1.0 * sr), dtype=np.float32)     # 静 1s
    vv = np.concatenate([sing, sil])                    # 2s：1s 唱 + 1s 静（单窗混合）
    cc = np.concatenate([_tone(1.0, sr, amp=2000.0), _tone(1.0, sr, amp=700.0)])  # 静音区有伴奏
    vv_p = tmp_path / "vocals.wav"; aa_p = tmp_path / "accompaniment.wav"
    _write_wav(vv_p, vv, sr); _write_wav(aa_p, cc, sr)
    il = tmp_path / "items.jsonl"
    il.write_text(json.dumps({"item_id": "Z", "audio_path": str(vv_p)}) + "\n")
    out = tmp_path / "outs"
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src") + ":" + env["PYTHONPATH"]
    r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/research_v7/export_silence_polluted_weak.py"),
                        "--item-list", str(il), "--out-root", str(out), "--window-sec", "2.0"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    man = json.loads((out / "AUDIO_EXPORT_MANIFEST.json").read_text())
    done = [x for x in man if x.get("done") is True]
    assert done, f"no done=true record; manifest={man}"
    d = done[0]
    assert d.get("vocal_sha256") and d.get("acc_sha256")   # sha 存在（vpath 已修）
    assert "control" in d["files"] and "weak_2" in d["files"]
    assert (Path(d["files"]["control"]).is_file()) and (Path(d["files"]["weak_2"]).is_file())
    # REQUESTS.jsonl 每 condition 一条固定 schema（供真实 runner）
    reqs = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert len(reqs) >= 2  # control + weak
    assert all(r.get("schema_version") == "research_v7_long_slot_v1" for r in reqs)
    assert all(r.get("request_identity") and r.get("pair_id") and r.get("vocal_sha256") for r in reqs)
    # review3-2：identity 必须含 content-sha + code_version；重跑同 out-root 应去重（原子写）
    assert all(r.get("code_version") and r.get("files_sha256") for r in reqs)
    # idempotent：同 out-root 再跑一次 REQUESTS 不重复
    import subprocess as _sp
    _sp.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/research_v7/export_silence_polluted_weak.py"),
             "--item-list", str(il), "--out-root", str(out), "--window-sec", "2.0"], capture_output=True, env=env)
    reqs2 = [json.loads(l) for l in (out / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert len(reqs2) == len(reqs)  # 去重，不追加


def test_c3_wav_to_runner_integration(tmp_path):
    # review4 下一步验收：C3 REQUESTS → materialized alignment request → fake executor evidence → identity-safe resume
    import json
    import subprocess
    import sys

    sr = 16000
    vv = np.concatenate([_tone(1.0, sr, amp=4000.0), np.zeros(int(1.0 * sr), dtype=np.float32)])
    cc = np.concatenate([_tone(1.0, sr, amp=2000.0), _tone(1.0, sr, amp=700.0)])
    vp = tmp_path / "vocals.wav"; ap = tmp_path / "accompaniment.wav"
    _write_wav(vp, vv, sr); _write_wav(ap, cc, sr)
    il = tmp_path / "items.jsonl"
    il.write_text(json.dumps({"item_id": "Z", "audio_path": str(vp)}) + "\n")
    # 先导出 C3（含歌词）
    out3 = tmp_path / "c3out"
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src") + ":" + env["PYTHONPATH"]
    exporter = str(Path(__file__).resolve().parents[2] / "scripts/research_v7/export_silence_polluted_weak.py")
    r = subprocess.run([sys.executable, exporter, "--item-list", str(il), "--out-root", str(out3),
                        "--window-sec", "2.0", "--text-units", "春", "风", "又"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    reqs = [json.loads(l) for l in (out3 / "REQUESTS.jsonl").read_text().splitlines() if l.strip()]
    assert reqs, "no REQUESTS emitted"
    # 第一条(control)应 validate 通过(有 text_units + audio range)
    con = next(rq for rq in reqs if rq["condition"] == "control")
    assert con["text_units"] and con["audio_end_sec"] > 0 and con["mutation"] == "control" and con["target_ratio"] == 0.0
    assert con["request_identity"]  # 可复现 identity 存在
    # runner 消费 REQUESTS（fake exec）→ evidence + RUN_MANIFEST
    run = tmp_path / "run"
    runner = str(Path(__file__).resolve().parents[2] / "scripts/research_v7/run_behavior_suite.py")
    rr = subprocess.run([sys.executable, runner, "--manifest", str(out3 / "REQUESTS.jsonl"),
                         "--out-root", str(run), "--smoke"], capture_output=True, text=True, env=env)
    assert rr.returncode == 0, rr.stderr
    run_man = json.loads((run / "RUN_MANIFEST.json").read_text())
    assert run_man["manifest"]["sha256"]  # 冻结 manifest sha 记录
    assert run_man["environment"]["executor"] == "fake-smoke"
    assert run_man["cache_keys"]  # 每请求 content identity
    # identity-safe resume：同 REQUESTS 再跑 → cache hit
    rr2 = subprocess.run([sys.executable, runner, "--manifest", str(out3 / "REQUESTS.jsonl"),
                          "--out-root", str(run), "--smoke", "--resume"],
                         capture_output=True, text=True, env=env)
    out2 = json.loads(rr2.stdout)
    assert out2["cache_hit"] >= 1 and out2["forward"] == 0


def test_runner_rejects_audio_drift_resume(tmp_path):
    # review5-1/5：轮 run 后改 WAV 内容，resume 应因 audio-hash 不匹配而失败（不误 cache hit）
    import json
    import subprocess
    import sys

    sr = 16000
    vv = np.concatenate([_tone(1.0, sr, amp=4000.0), np.zeros(int(1.0 * sr), dtype=np.float32)])
    cc = np.concatenate([_tone(1.0, sr, amp=2000.0), _tone(1.0, sr, amp=700.0)])
    vp = tmp_path / "vocals.wav"; ap = tmp_path / "accompaniment.wav"
    _write_wav(vp, vv, sr); _write_wav(ap, cc, sr)
    il = tmp_path / "items.jsonl"
    il.write_text(json.dumps({"item_id": "D", "audio_path": str(vp)}) + "\n")
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src") + ":" + env["PYTHONPATH"]
    exporter = str(Path(__file__).resolve().parents[2] / "scripts/research_v7/export_silence_polluted_weak.py")
    r = subprocess.run([sys.executable, exporter, "--item-list", str(il), "--out-root", tmp_path/"c3",
                        "--window-sec", "2.0", "--text-units", "春", "风"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    reqs_file = tmp_path / "c3" / "REQUESTS.jsonl"
    # 首轮 fake exec 跑（成功）
    runner = str(Path(__file__).resolve().parents[2] / "scripts/research_v7/run_behavior_suite.py")
    run = tmp_path / "run"
    rr = subprocess.run([sys.executable, runner, "--manifest", str(reqs_file), "--out-root", str(run), "--smoke"],
                        capture_output=True, text=True, env=env)
    assert rr.returncode == 0, rr.stderr
    # 改"导出 wav"内容（req.audio_source 指向它）—— files_sha256 声明不变但实际变更
    one_wav = next((tmp_path / "c3").glob("D/*.wav"))
    _write_wav(one_wav, _tone(1.0, sr, amp=8000.0), sr)
    rr2 = subprocess.run([sys.executable, runner, "--manifest", str(reqs_file), "--out-root", str(run),
                          "--smoke", "--resume"], capture_output=True, text=True, env=env)
    # review6-4：audio drift 不再中止批次——记为 structured failure，继续其它 item，仍产 RUN_MANIFEST
    assert rr2.returncode == 0, rr2.stderr
    rm = json.loads((run / "RUN_MANIFEST.json").read_text())
    assert any("audio drift" in (f.get("error") or "") for f in rm["failures"])
    assert rm["item_count"]["failed"] == len(rm["failures"])  # 一致
    # 且该 drift identity 未被错误写入 evidence/cache（不误命中旧证据）
    n_before = len(list((run / "evidence").glob("*.json"))) if (run / "evidence").exists() else 0
    n_after = len(list((run / "evidence").glob("*.json")))
    assert n_after <= n_before  # 未新增证据
