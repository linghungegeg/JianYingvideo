import json
import os
import subprocess
from typing import List, Tuple, Dict, Optional
from app.utils.ffmpeg_utils import find_ffmpeg, find_ffprobe


def ensure_dir(path: str):
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def list_video_files(root_path: str) -> List[str]:
    exts = (".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v")
    if os.path.isfile(root_path):
        return [root_path]
    files = []
    for root, _dirs, fnames in os.walk(root_path):
        for fname in fnames:
            if fname.lower().endswith(exts):
                files.append(os.path.join(root, fname))
    return files


def probe_video_info(path: str) -> Dict[str, Optional[float]]:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return {"width": None, "height": None, "fps": None, "duration": None}
    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        path
    ]
    try:
        out = subprocess.check_output(cmd)
        data = json.loads(out.decode("utf-8"))
        stream = (data.get("streams") or [{}])[0]
        width = stream.get("width")
        height = stream.get("height")
        fps = None
        r = stream.get("r_frame_rate")
        if r and isinstance(r, str) and "/" in r:
            num, den = r.split("/", 1)
            try:
                fps = float(num) / float(den)
            except Exception:
                fps = None
        duration = None
        try:
            duration = float((data.get("format") or {}).get("duration"))
        except Exception:
            duration = None
        return {"width": width, "height": height, "fps": fps, "duration": duration}
    except Exception:
        return {"width": None, "height": None, "fps": None, "duration": None}


def split_fixed_duration(input_path: str, output_dir: str, segment_seconds: float) -> List[str]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    ensure_dir(output_dir)
    base = os.path.splitext(os.path.basename(input_path))[0]
    out_pattern = os.path.join(output_dir, f"{base}_%03d.mp4")
    cmd = [
        ffmpeg, "-y", "-i", input_path,
        "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1",
        out_pattern
    ]
    subprocess.check_call(cmd)
    # collect outputs
    outputs = []
    for fname in sorted(os.listdir(output_dir)):
        if fname.startswith(base + "_") and fname.lower().endswith(".mp4"):
            outputs.append(os.path.join(output_dir, fname))
    return outputs


def split_by_count(input_path: str, output_dir: str, count: int) -> List[str]:
    info = probe_video_info(input_path)
    duration = info.get("duration")
    if not duration or count <= 0:
        raise RuntimeError("invalid duration or count")
    segment_seconds = max(1.0, float(duration) / float(count))
    return split_fixed_duration(input_path, output_dir, segment_seconds)


def detect_scenes(input_path: str, threshold: float = 30.0, min_scene_len: int = 15) -> List[Tuple[float, float]]:
    try:
        from scenedetect import VideoManager, SceneManager
        from scenedetect.detectors import ContentDetector
    except Exception as e:
        raise RuntimeError(f"PySceneDetect not available: {e}")
    video_manager = VideoManager([input_path])
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    scenes = scene_manager.get_scene_list()
    result = []
    for start, end in scenes:
        result.append((start.get_seconds(), end.get_seconds()))
    return result


def split_by_scenes(input_path: str, output_dir: str, scenes: List[Tuple[float, float]]) -> List[str]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    ensure_dir(output_dir)
    base = os.path.splitext(os.path.basename(input_path))[0]
    outputs = []
    for idx, (start, end) in enumerate(scenes):
        if end <= start:
            continue
        out_path = os.path.join(output_dir, f"{base}_scene_{idx:03d}.mp4")
        cmd = [
            ffmpeg, "-y", "-i", input_path,
            "-ss", str(start), "-to", str(end),
            "-c", "copy",
            out_path
        ]
        subprocess.check_call(cmd)
        outputs.append(out_path)
    return outputs


def detect_silences(input_path: str, silence_db: float = -35.0, min_silence: float = 0.4) -> List[Tuple[float, float]]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    cmd = [
        ffmpeg, "-i", input_path,
        "-af", f"silencedetect=noise={silence_db}dB:d={min_silence}",
        "-f", "null", "-"
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        log = (proc.stderr or b"").decode("utf-8", errors="ignore")
    except Exception as e:
        raise RuntimeError(f"ffmpeg silencedetect failed: {e}")

    starts = []
    ends = []
    for line in log.splitlines():
        line = line.strip()
        if "silence_start" in line:
            try:
                starts.append(float(line.split("silence_start:")[-1].strip()))
            except Exception:
                continue
        if "silence_end" in line:
            try:
                tail = line.split("silence_end:")[-1].strip()
                ends.append(float(tail.split(" ")[0]))
            except Exception:
                continue
    if not starts or not ends:
        return []
    silences = list(zip(starts, ends))
    return [(s, e) for s, e in silences if e > s]


def split_by_silence(input_path: str, output_dir: str, silences: List[Tuple[float, float]]) -> List[str]:
    info = probe_video_info(input_path)
    duration = info.get("duration") or 0
    if duration <= 0:
        raise RuntimeError("invalid duration")
    # build segments between silences
    points = [0.0]
    for s, e in silences:
        points.append(s)
        points.append(e)
    points.append(duration)
    points = sorted(set(p for p in points if p >= 0))
    segments = []
    last = 0.0
    for p in points:
        if p - last > 0.2:
            segments.append((last, p))
        last = p
    return split_by_scenes(input_path, output_dir, segments)


def _parse_srt_time(t: str) -> Optional[float]:
    # format: HH:MM:SS,mmm
    try:
        hms, ms = t.split(",", 1)
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s) + (int(ms) / 1000.0)
    except Exception:
        return None


def parse_srt_segments(srt_path: str) -> List[Tuple[float, float]]:
    if not os.path.exists(srt_path):
        raise RuntimeError("srt not found")
    try:
        raw = open(srt_path, "r", encoding="utf-8").read()
    except Exception:
        raw = open(srt_path, "r", encoding="utf-8-sig").read()
    segments: List[Tuple[float, float]] = []
    for line in raw.splitlines():
        line = line.strip()
        if "-->" in line:
            parts = [p.strip() for p in line.split("-->")]
            if len(parts) != 2:
                continue
            start = _parse_srt_time(parts[0])
            end = _parse_srt_time(parts[1])
            if start is None or end is None:
                continue
            if end > start:
                segments.append((start, end))
    return segments


def _merge_subtitle_segments(
    segments: List[Tuple[float, float]],
    max_gap: float = 0.2,
    min_duration: float = 0.3
) -> List[Tuple[float, float]]:
    if not segments:
        return []
    merged: List[Tuple[float, float]] = []
    for start, end in sorted(segments, key=lambda x: x[0]):
        if end <= start:
            continue
        if not merged:
            merged.append((start, end))
            continue
        last_start, last_end = merged[-1]
        if start - last_end <= max_gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return [(s, e) for s, e in merged if e - s >= min_duration]


def split_by_subtitles(input_path: str, output_dir: str, srt_path: str) -> List[str]:
    segments = parse_srt_segments(srt_path)
    if not segments:
        raise RuntimeError("no subtitle segments")
    segments = _merge_subtitle_segments(segments)
    if not segments:
        raise RuntimeError("subtitle segments too short after merge")
    return split_by_scenes(input_path, output_dir, segments)
