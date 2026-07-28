"""Encode fixed-scale diagnostic PNG pages into resumable review videos."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .karaoke import ass_escape
from .media_render import VideoGeometry, atomic_json, build_bottom_ass, canonical_hash, sha256


def _ffmpeg_escape(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def render_page_video(
    *, pages: list[dict[str, Any]], alignment: dict[str, Any], audio_track: Path,
    output_path: Path, work_root: Path, font: str, title: str,
    profile: str = "review", force: bool = False, include_karaoke: bool = True,
) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    if not pages:
        raise ValueError(f"no visual pages supplied for {title}")
    page_paths=[Path(str(page["path"])).resolve() for page in pages]
    missing=[str(path) for path in page_paths if not path.is_file() or path.stat().st_size<=0]
    if missing: raise FileNotFoundError(f"video page missing: {missing}")
    settings={
        "review":{"fps":12,"preset":"veryfast","crf":29,"audio_bitrate":"96k"},
        "final":{"fps":24,"preset":"medium","crf":20,"audio_bitrate":"192k"},
    }[profile]
    page_seconds=float(pages[0]["end_sec"])-float(pages[0]["start_sec"])
    page_seconds=max(1.0,page_seconds)
    duration=float((alignment.get("summary") or {}).get("audio_duration_sec",pages[-1]["end_sec"]))
    request={
        "schema_version":"inline_realign_timeline_video_v2",
        "title":title,"pages":[{"path":str(path),"sha256":sha256(path),"start":page.get("start_sec"),"end":page.get("end_sec")} for path,page in zip(page_paths,pages)],
        "audio_sha256":sha256(audio_track),"font":font,"profile":profile,"include_karaoke":include_karaoke,
        "duration_sec":duration,"page_seconds":page_seconds,"settings":settings,
    }
    request_hash=canonical_hash(request); identity_path=output_path.with_suffix(output_path.suffix+".identity.json")
    if not force and output_path.is_file() and identity_path.is_file():
        old=json.loads(identity_path.read_text(encoding="utf-8"))
        if old.get("request_hash")==request_hash:
            return {"path":str(output_path),"request_hash":request_hash,"skipped":True}
    work_root.mkdir(parents=True,exist_ok=True); output_path.parent.mkdir(parents=True,exist_ok=True)
    concat_path=work_root/f"{output_path.stem}.pages.txt"
    lines=[]
    for page,path in zip(pages,page_paths):
        page_duration=max(0.01,float(page["end_sec"])-float(page["start_sec"]))
        lines.extend([f"file '{str(path).replace("'", "'\\''")}'",f"duration {page_duration:.9f}"])
    lines.append(f"file '{str(page_paths[-1]).replace("'", "'\\''")}'")
    concat_path.write_text("\n".join(lines)+"\n",encoding="utf-8")
    filters=[f"fps={settings['fps']}","scale=1920:1080:force_original_aspect_ratio=decrease","pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"]
    # Reset the pointer at each fixed-scale page.  The final shortened page may
    # end before reaching the right edge, which correctly reflects song end.
    filters.append(f"drawbox=x='min(iw-5,mod(t,{page_seconds:.9f})/{page_seconds:.9f}*iw)':y=0:w=5:h=ih:color=white@0.92:t=fill")
    if include_karaoke:
        geometry=VideoGeometry(width=1920,source_height=1080,subtitle_band_height=190,canvas_height=1080)
        ass_path=work_root/f"{output_path.stem}.ass"
        # build_bottom_ass uses Chinese lyric glyphs and a compact lower band.
        ass_path.write_text(build_bottom_ass(alignment,label=title,font=font,geometry=geometry),encoding="utf-8")
        filters.append(f"ass='{_ffmpeg_escape(ass_path)}'")
    temporary=output_path.with_suffix(".tmp.mp4")
    command=["ffmpeg","-nostdin","-y","-v","warning","-f","concat","-safe","0","-i",str(concat_path),"-i",str(audio_track),"-vf",",".join(filters),"-map","0:v:0","-map","1:a:0","-t",f"{duration:.6f}","-r",str(settings["fps"]),"-c:v","libx264","-preset",settings["preset"],"-crf",str(settings["crf"]),"-pix_fmt","yuv420p","-c:a","aac","-b:a",settings["audio_bitrate"],"-movflags","+faststart",str(temporary)]
    subprocess.run(command,check=True,cwd=work_root)
    temporary.replace(output_path); atomic_json(identity_path,{**request,"request_hash":request_hash,"command":command})
    return {"path":str(output_path),"request_hash":request_hash,"skipped":False,"page_count":len(pages)}
