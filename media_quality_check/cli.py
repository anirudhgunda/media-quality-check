#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path

FILE_MEDIA_SCORE = {}


def run_ffprobe(file):
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(file)
    ]
    return json.loads(subprocess.check_output(cmd))


def print_separator(width=120):
    print("=" * width)


def detect_dolby_vision(video_stream):
    for sd in video_stream.get("side_data_list", []):
        sdt = (sd.get("side_data_type") or "").lower()
        if "dovi" in sdt or "dolby vision" in sdt:
            return True
    tag = (video_stream.get("codec_tag_string") or "").lower()
    return tag in ("dvh1", "dvhe")


def compute_video_score(v, fmt, is_hdr, is_dv):
    width = v.get("width", 0)
    height = v.get("height", 0)
    pixels = width * height
    mp = pixels / 1_000_000 if pixels else 0.01

    size = float(fmt.get("size", 0))
    duration = float(fmt.get("duration", 1))
    bitrate_mbps = (size * 8) / duration / 1_000_000

    # Base score
    score = 0.0
    verdict = "MEDIUM"

    if width >= 3840:  # 4K
        if is_dv or is_hdr:
            if bitrate_mbps >= 15:
                score = 5.0
                verdict = "REFERENCE QUALITY"
            else:
                score = 4.5
                verdict = "EXCELLENT"
        else:  # 4K SDR
            if bitrate_mbps >= 20:
                score = 4.5
                verdict = "EXCELLENT"
            else:
                score = 4.0
                verdict = "GOOD"
    elif width >= 1920:  # 1080p
        if bitrate_mbps >= 25:
            score = 4.5
            verdict = "EXCELLENT"
        elif is_dv or is_hdr:
            score = 4.5
            verdict = "EXCELLENT"
        else:
            score = 4.0
            verdict = "GOOD"
    elif width >= 1280:  # 720p
        if bitrate_mbps >= 10:
            score = 3.5
            verdict = "GOOD"
        else:
            score = 3.0
            verdict = "MEDIUM"
    else:  # lower resolutions
        score = 2.0
        verdict = "MEDIUM"

    return score, bitrate_mbps, verdict


def compute_audio_score(streams):
    best = 0.0
    for a in streams:
        if a.get("codec_type") != "audio":
            continue

        codec = a.get("codec_name", "")
        ch = a.get("channels", 0)
        profile = (a.get("profile") or "").lower()

        lossless = codec == "truehd" or (codec.startswith("dts") and "hd" in profile)
        atmos = "atmos" in profile

        base = {
            "truehd": 5.0,
            "dts": 4.5,
            "eac3": 3.5,
            "ac3": 3.0,
            "aac": 2.0
        }.get(codec.split("_")[0], 0)

        bonus = 0
        if atmos:
            bonus += 0.5
        if ch >= 8:
            bonus += 0.5
        elif ch >= 6:
            bonus += 0.3

        score = min(base + bonus, 5.0)
        best = max(best, score)

    return best


def analyze_file(file):
    file = Path(file)
    if not file.exists():
        print(f"File not found: {file}")
        return

    print_separator()
    print(f"📁 File: {file}")
    print_separator()

    data = run_ffprobe(file)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_streams = [
        s for s in streams
        if s.get("codec_type") == "video"
        and s.get("disposition", {}).get("attached_pic", 0) != 1
    ]

    print("🎥 Video Streams:")
    is_hdr = False
    is_dv = False
    for v in video_streams:
        pix_fmt = v.get("pix_fmt", "")
        transfer = v.get("color_transfer", "")
        bitdepth = "10-bit" if "10" in pix_fmt else "8-bit"
        dovi = detect_dolby_vision(v)

        if dovi:
            hdr_label = "Dolby Vision"
            is_dv = True
            is_hdr = True
        elif transfer in ("smpte2084", "arib-std-b67"):
            hdr_label = "HDR"
            is_hdr = True
        else:
            hdr_label = "SDR"

        size = float(fmt.get("size", 0))
        duration = float(fmt.get("duration", 1))
        vbps = (size * 8) / duration / 1_000_000

        print(
            f"  ▸ {v.get('codec_name')} | {v.get('width')}x{v.get('height')} | "
            f"{bitdepth} | {hdr_label} | {vbps:.2f} Mbps"
        )

    best_video = max(video_streams, key=lambda x: x.get("width", 0))
    video_score, vbps, video_verdict = compute_video_score(best_video, fmt, is_hdr, is_dv)

    print("\n🔊 Audio Streams:")
    for a in [s for s in streams if s.get("codec_type") == "audio"]:
        codec = a.get("codec_name", "")
        ch = a.get("channels", 0)
        lang = a.get("tags", {}).get("language", "und")
        raw_br = a.get("bit_rate") or a.get("tags", {}).get("BPS")
        br = f"{int(int(raw_br)/1000)} kbps" if raw_br else "NA"
        print(f"  ▸ {codec} | {ch}ch | {br} | LANG: {lang}")

    audio_score = compute_audio_score(streams)

    # Weighted media score
    media_score = round(min(video_score * 0.7 + audio_score * 0.3, 5.0), 2)
    FILE_MEDIA_SCORE[str(file)] = (media_score, vbps)

    print(f"\n📊 Media Score: {media_score} / 5.0")
    print(f"\n🏁 Verdict: {video_verdict}")
    print_separator()


def main():
    if len(sys.argv) < 2:
        print("Usage: media-quality-check <video-file> [video-file2 ...]")
        sys.exit(1)

    for f in sys.argv[1:]:
        analyze_file(f)

    if len(sys.argv) > 2:
        # Pick file with highest media score, tiebreak with highest video bitrate
        best_file = max(
            FILE_MEDIA_SCORE.items(),
            key=lambda x: (x[1][0], x[1][1])
        )[0]
        display = best_file if len(best_file) <= 100 else "..." + best_file[-97:]
        print(f"✅ Preferred File: {display}")
        print_separator()


if __name__ == "__main__":
    main()

