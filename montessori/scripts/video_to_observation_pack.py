#!/usr/bin/env python3
"""
Create a Montessori observation pack from a local video.

Outputs:
- frames/frame_0001_00-00-02.jpg ... sampled key frames
- contact_sheet.jpg if ffmpeg tile succeeds
- audio.wav if audio exists and --extract-audio is set
- observation_pack.md with metadata, frame timeline, optional transcript section

Security: local-only script. No network requests. No telemetry. No deletion.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from datetime import timedelta

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def require_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Missing required binary: {name}. Please install ffmpeg first.")
    return path


def fmt_ts(seconds: float) -> str:
    seconds = max(0, float(seconds))
    td = timedelta(seconds=int(round(seconds)))
    total = int(td.total_seconds())
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}-{m:02d}-{s:02d}"


def probe(video: Path) -> dict:
    """Return ffprobe-like metadata. Falls back to ffmpeg stderr parsing if ffprobe is absent."""
    if shutil.which("ffprobe"):
        cmd = [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(video),
        ]
        cp = run(cmd)
        return json.loads(cp.stdout)

    require_bin("ffmpeg")
    cp = run(["ffmpeg", "-i", str(video)], check=False)
    text = (cp.stderr or "") + (cp.stdout or "")
    meta: dict = {"format": {}, "streams": []}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        h, mi, sec = m.groups()
        meta["format"]["duration"] = str(int(h) * 3600 + int(mi) * 60 + float(sec))
    vm = re.search(r"Video:.*?,\s*(\d+)x(\d+)", text)
    if vm:
        meta["streams"].append({"codec_type": "video", "width": int(vm.group(1)), "height": int(vm.group(2))})
    if "Audio:" in text:
        meta["streams"].append({"codec_type": "audio"})
    return meta


def get_duration(meta: dict) -> float:
    try:
        return float(meta.get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


def has_audio(meta: dict) -> bool:
    return any(s.get("codec_type") == "audio" for s in meta.get("streams", []))


def video_size(meta: dict) -> tuple[int | None, int | None]:
    for s in meta.get("streams", []):
        if s.get("codec_type") == "video":
            return s.get("width"), s.get("height")
    return None, None


def extract_frame(video: Path, out: Path, at: float, width: int) -> bool:
    require_bin("ffmpeg")
    vf = f"scale={width}:-2" if width > 0 else "scale=960:-2"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(0, at)),
        "-i", str(video),
        "-frames:v", "1",
        "-vf", vf,
        "-q:v", "2",
        str(out),
    ]
    cp = run(cmd, check=False)
    return cp.returncode == 0 and out.exists() and out.stat().st_size > 0


def extract_audio(video: Path, out: Path) -> bool:
    require_bin("ffmpeg")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000",
        str(out),
    ]
    cp = run(cmd, check=False)
    return cp.returncode == 0 and out.exists() and out.stat().st_size > 0


def make_contact_sheet(frames_dir: Path, out: Path, cols: int) -> bool:
    require_bin("ffmpeg")
    pattern = str(frames_dir / "frame_%04d_*.jpg")
    # ffmpeg does not support glob with %04d and timestamp suffix reliably, so use concat list.
    files = sorted(frames_dir.glob("frame_*.jpg"))
    if not files:
        return False
    list_file = frames_dir / "frames.txt"
    list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in files))
    rows = math.ceil(len(files) / max(1, cols))
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-vf", f"scale=360:-2,tile={cols}x{rows}:padding=8:margin=8",
        "-frames:v", "1",
        str(out),
    ]
    cp = run(cmd, check=False)
    return cp.returncode == 0 and out.exists() and out.stat().st_size > 0



def extract_frames_cv2(video: Path, frames_dir: Path, interval: float, max_frames: int, width: int) -> tuple[list[tuple[int, float, Path]], float, int, int | None, int | None]:
    if cv2 is None or Image is None:
        return [], 0.0, 0, None, None
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return [], 0.0, 0, None, None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = count / fps if fps else 0.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or None
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or None
    sample_interval = max(0.05, interval)
    times = [0] if duration <= 0 else [i * sample_interval for i in range(int(duration // sample_interval) + 1)]
    if len(times) > max_frames:
        step = max(1, math.ceil(len(times) / max_frames))
        times = times[::step][:max_frames]
    rows: list[tuple[int, float, Path]] = []
    for idx, t in enumerate(times, start=1):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        fh, fw = frame.shape[:2]
        neww = width if width > 0 else 960
        newh = int(fh * neww / fw)
        frame = cv2.resize(frame, (neww, newh))
        img = Image.fromarray(frame)
        draw = ImageDraw.Draw(img)
        label = f"{idx:02d}  {t:.1f}s"
        draw.rectangle([8, 8, 150, 42], fill=(255, 255, 255))
        draw.text((14, 16), label, fill=(0, 0, 0))
        fp = frames_dir / f"frame_{idx:04d}_{fmt_ts(t)}.jpg"
        img.save(fp, quality=92)
        rows.append((idx, t, fp))
    cap.release()
    return rows, duration, count, w, h


def make_contact_sheet_pil(frames_dir: Path, out: Path, cols: int) -> bool:
    if Image is None:
        return False
    files = sorted(frames_dir.glob("frame_*.jpg"))
    if not files:
        return False
    thumbs = []
    for f in files:
        img = Image.open(f)
        neww = 260
        img = img.resize((neww, int(img.height * neww / img.width)))
        thumbs.append(img)
    rows = math.ceil(len(thumbs) / max(1, cols))
    tw = max(i.width for i in thumbs)
    th = max(i.height for i in thumbs)
    sheet = Image.new("RGB", (cols * tw, rows * th), (245, 245, 245))
    for n, img in enumerate(thumbs):
        sheet.paste(img, ((n % cols) * tw, (n // cols) * th))
    sheet.save(out, quality=90)
    return out.exists() and out.stat().st_size > 0

def main() -> None:
    ap = argparse.ArgumentParser(description="Create a local video observation pack for eeailab-montessori.")
    ap.add_argument("video", help="Input video path")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--interval", type=float, default=0.5, help="Sample one frame every N seconds; use 0.2-0.5 for behavior observation")
    ap.add_argument("--max-frames", type=int, default=120, help="Maximum frames to extract; increase for longer videos")
    ap.add_argument("--width", type=int, default=960, help="Frame output width")
    ap.add_argument("--extract-audio", action="store_true", help="Extract mono 16k wav audio")
    ap.add_argument("--transcript", help="Optional existing transcript txt path")
    ap.add_argument("--child-age", default="", help="Optional child age, written to md")
    ap.add_argument("--question", default="", help="Optional user question, written to md")
    args = ap.parse_args()

    video = Path(args.video).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")

    out = Path(args.out).expanduser().resolve()
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    meta = probe(video)
    duration = get_duration(meta)
    width, height = video_size(meta)

    if duration <= 0:
        # fallback: still try first frame
        times = [0]
    else:
        interval = max(0.05, args.interval)
        times = [i * interval for i in range(int(duration // interval) + 1)]
        if len(times) > args.max_frames:
            step = max(1, math.ceil(len(times) / args.max_frames))
            times = times[::step][: args.max_frames]

    frame_rows: list[tuple[int, float, Path]] = []
    for idx, t in enumerate(times, start=1):
        name = f"frame_{idx:04d}_{fmt_ts(t)}.jpg"
        fp = frames_dir / name
        if extract_frame(video, fp, t, args.width):
            frame_rows.append((idx, t, fp))

    # Some packaged ffmpeg builds cannot decode normal mp4/mov. Fall back to OpenCV when available.
    if not frame_rows:
        frame_rows, cv_duration, cv_count, cv_width, cv_height = extract_frames_cv2(video, frames_dir, args.interval, args.max_frames, args.width)
        if cv_duration:
            duration = cv_duration
        if cv_width and cv_height:
            width, height = cv_width, cv_height

    if not frame_rows:
        raise SystemExit(
            "Could not extract any frame from this video. Install a standard ffmpeg build or Python OpenCV/Pillow, then retry."
        )

    contact = out / "contact_sheet.jpg"
    contact_ok = make_contact_sheet(frames_dir, contact, cols=4)
    if not contact_ok:
        contact_ok = make_contact_sheet_pil(frames_dir, contact, cols=4)

    audio_path = out / "audio.wav"
    audio_ok = False
    if args.extract_audio and has_audio(meta):
        audio_ok = extract_audio(video, audio_path)

    transcript_text = ""
    if args.transcript:
        tp = Path(args.transcript).expanduser().resolve()
        if tp.exists():
            transcript_text = tp.read_text(errors="ignore").strip()

    md = out / "observation_pack.md"
    lines: list[str] = []
    lines.append("# 蒙氏视频观察包")
    lines.append("")
    lines.append("## 基本信息")
    lines.append("")
    lines.append(f"- 视频文件：`{video}`")
    lines.append(f"- 时长：{duration:.1f} 秒" if duration else "- 时长：未识别")
    lines.append(f"- 原始尺寸：{width}x{height}" if width and height else "- 原始尺寸：未识别")
    if args.child_age:
        lines.append(f"- 孩子年龄：{args.child_age}")
    if args.question:
        lines.append(f"- 用户问题：{args.question}")
    lines.append(f"- 抽帧数量：{len(frame_rows)}")
    if contact_ok:
        lines.append(f"- 总览图：`{contact}`")
    if audio_ok:
        lines.append(f"- 音频文件：`{audio_path}`")
    lines.append("")
    lines.append("## 关键帧时间轴")
    lines.append("")
    lines.append("| 序号 | 时间点 | 图片 | 观察备注 |")
    lines.append("|---:|---:|---|---|")
    for idx, t, fp in frame_rows:
        lines.append(f"| {idx} | {t:.1f}s | `{fp.name}` |  |")
    lines.append("")
    lines.append("## 音频 / 对话转写")
    lines.append("")
    if transcript_text:
        lines.append(transcript_text)
    elif audio_ok:
        lines.append("已提取音频，但尚未转写。可以使用任意 ASR 工具转写后补到这里。")
    else:
        lines.append("未提供转写。若视频中成人语言很关键，请补充大概对话。")
    lines.append("")
    lines.append("## 给 eeailab-montessori 的分析提示")
    lines.append("")
    lines.append("请基于关键帧、时间轴、音频 / 对话转写和用户问题，按蒙氏家庭观察框架输出：")
    lines.append("")
    lines.append("1. 行为观察：只描述看见的事实，不急着贴标签。")
    lines.append("2. 可能的发展需求：秩序感、独立性、感官探索、运动练习、语言互动、边界测试等。")
    lines.append("3. 环境线索：空间、物品高度、可及性、动线、成人干预。")
    lines.append("4. 家长回应建议：下一次怎么说、怎么示范、怎么设边界。")
    lines.append("5. 可替代活动：给 2-3 个家庭可执行活动。")
    lines.append("6. 边界提醒：不做医学、心理、发育诊断。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Origin marker: `eeailab-origin-2026-yiyi-growth-lab`  ")
    lines.append("Slogan: AI时代不做第一，只做唯一")
    lines.append("Contact: 抖音 / 小红书：伊伊的 AI 成长实验室；微信：xiaofulab")
    md.write_text("\n".join(lines))

    print(md)


if __name__ == "__main__":
    main()
