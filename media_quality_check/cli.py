#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path

FILE_SCORES = {}
FILE_VIDEO_SCORE = {}
FILE_AUDIO_SCORE = {}


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

    # --------------------
    # VIDEO
    # --------------------
    video_streams = [
        s for s in streams
        if s.get("codec_type") == "video"
        and s.get("disposition", {}).get("attached_pic", 0) != 1
    ]

    print("🎥 Video Streams:")
    for v in video_streams:
        bitdepth = "10-bit" if "10" in (v.get("pix_fmt") or "") else "8-bit"
        hdr = "HDR" if (v.get("color_transfer") in ("smpte2084", "arib-std-b67")) else "SDR"
        print(
            f"  ▸ [V:{v.get('index')}] "
            f"{v.get('codec_name')} | "
            f"{v.get('width')}x{v.get('height')} | "
            f"{bitdepth} | {hdr}"
        )

    best_video = max(video_streams, key=lambda x: x.get("width", 0), default={})

    width = best_video.get("width", 0)
    pix_fmt = best_video.get("pix_fmt", "")
    transfer = best_video.get("color_transfer", "")

    size = float(fmt.get("size", 0))
    duration = float(fmt.get("duration", 1))
    vbps = (size * 8) / duration / 1_000_000

    bitdepth = "10-bit" if "10" in pix_fmt else "8-bit"
    hdr = "HDR" if transfer in ("smpte2084", "arib-std-b67") else "SDR"

    # Dolby Vision detection
    dovi = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_streams", "-select_streams", "v:0", str(file)],
        stdout=subprocess.PIPE,
        text=True
    ).stdout
    dovi = 1 if "DOVI" in dovi else 0

    video_score = 0
    if width >= 3840 and (bitdepth == "10-bit" or dovi) and hdr == "HDR":
        video_score = 6 if vbps >= 12 else 5
    elif width >= 3840:
        video_score = 5 if vbps >= 12 else 4
    elif width >= 1920:
        if vbps >= 25:
            video_score = 5
        elif vbps >= 15:
            video_score = 4
        else:
            video_score = 3
    else:
        video_score = 1

    print(f"\n📊 Video Score: {video_score} / 6 ({vbps:.2f} Mbps)")

    # --------------------
    # AUDIO
    # --------------------
    print("\n🔊 Audio Streams:")

    best_audio_score = 0
    best_audio_label = ""
    audio_prior_score = 0

    for a in [s for s in streams if s.get("codec_type") == "audio"]:
        codec = a.get("codec_name")
        ch = a.get("channels", 0)
        lang = a.get("tags", {}).get("language", "und")
        profile = a.get("profile", "")

        if codec.startswith("dts") and lang == "und":
            lang = "tel"

        lossless = codec == "truehd" or (codec.startswith("dts") and "HD" in profile)
        br = "LOSSLESS"

        if not lossless:
            raw_br = a.get("bit_rate") or a.get("tags", {}).get("BPS")
            if raw_br:
                br = f"{int(int(raw_br) / 1000)} kbps"

        atmos = 1 if "atmos" in profile.lower() else 0

        base = {
            "truehd": 6,
            "dts": 5,
            "eac3": 4,
            "ac3": 3,
            "aac": 1
        }.get(codec.split("_")[0], 0)

        bonus = 0
        bonus += 2 if atmos else 0
        bonus += 1 if lang == "tel" else 0
        bonus += 1 if ch >= 7 else 0

        score = min(base + bonus, 7)

        print(
            f"  ▸ {codec} | {ch}ch | {br} | LANG: {lang}"
            f"{' | Atmos' if atmos else ''}"
        )

        if score > best_audio_score:
            best_audio_score = score
            best_audio_label = f"{codec}{' + Atmos' if atmos else ''} [{lang}]"
            audio_prior_score = base * 10 + bonus

    print(f"🎧 Audio Score: {best_audio_score} / 7")
    print(f"🎯 Best Audio: {best_audio_label}")

    total = video_score + best_audio_score

    if video_score == 6 and best_audio_score >= 6:
        verdict = "REFERENCE QUALITY"

    elif video_score == 5 and best_audio_score >= 5:
        verdict = "EXCELLENT"

    elif video_score == 4 and best_audio_score >= 6:
        verdict = "EXCELLENT"

    elif video_score == 4 and best_audio_score >= 4:
        verdict = "GOOD"

    else:
        verdict = "MEDIUM"

    print(f"🏁 Verdict: {verdict}")
    print_separator()

    FILE_SCORES[str(file)] = total
    FILE_VIDEO_SCORE[str(file)] = video_score
    FILE_AUDIO_SCORE[str(file)] = audio_prior_score


def main():
    if len(sys.argv) < 2:
        print("Usage: media-quality-check <video-file> [video-file2 ...]")
        sys.exit(1)

    for f in sys.argv[1:]:
        analyze_file(f)

    if len(sys.argv) > 2:
        best_file = ""
        best_score = 0

        for f in sys.argv[1:]:
            score = FILE_VIDEO_SCORE[f] * 10 + FILE_AUDIO_SCORE[f]
            if score > best_score:
                best_score = score
                best_file = f

        display = best_file if len(best_file) <= 100 else "..." + best_file[-97:]
        print(f"✅ Preferred File: {display}")
        print_separator()


if __name__ == "__main__":
    main()

