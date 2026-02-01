#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path

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


def detect_dolby_vision(video_stream):
    for sd in video_stream.get("side_data_list", []):
        sdt = (sd.get("side_data_type") or "").lower()
        if "dovi" in sdt or "dolby vision" in sdt:
            return True

    tag = (video_stream.get("codec_tag_string") or "").lower()
    if tag in ("dvh1", "dvhe"):
        return True

    return False


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

    # ====================
    # VIDEO
    # ====================
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

        print(
            f"  ▸ [V:{v.get('index')}] "
            f"{v.get('codec_name')} | "
            f"{v.get('width')}x{v.get('height')} | "
            f"{bitdepth} | {hdr_label}"
        )

    best_video = max(video_streams, key=lambda x: x.get("width", 0), default={})

    width = best_video.get("width", 0)
    pix_fmt = best_video.get("pix_fmt", "")
    bitdepth = "10-bit" if "10" in pix_fmt else "8-bit"

    size = float(fmt.get("size", 0))
    duration = float(fmt.get("duration", 1))
    vbps = (size * 8) / duration / 1_000_000

    # --------------------
    # Video scoring
    # --------------------
    video_score = 0

    if width >= 3840 and (bitdepth == "10-bit" or is_dv):
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

    # ====================
    # AUDIO
    # ====================
    print("\n🔊 Audio Streams:")

    best_audio_score = 0
    audio_priority_score = 0

    for a in [s for s in streams if s.get("codec_type") == "audio"]:
        codec = a.get("codec_name", "")
        ch = a.get("channels", 0)
        lang = a.get("tags", {}).get("language", "und")
        profile = (a.get("profile") or "").lower()

        if codec.startswith("dts") and lang == "und":
            lang = "tel"

        lossless = codec == "truehd" or (codec.startswith("dts") and "hd" in profile)
        atmos = "atmos" in profile

        if lossless:
            br = "LOSSLESS"
        else:
            raw_br = a.get("bit_rate") or a.get("tags", {}).get("BPS")
            br = f"{int(int(raw_br) / 1000)} kbps" if raw_br else "NA"

        base = {
            "truehd": 6,
            "dts": 5,
            "eac3": 4,
            "ac3": 3,
            "aac": 3
        }.get(codec.split("_")[0], 0)

        bonus = 0
        bonus += 2 if atmos else 0
        bonus += 1 if lang == "tel" else 0
        if ch >= 8:
            bonus += 2
        elif ch >= 6:
            bonus += 1

        score = min(base + bonus, 7)

        print(
            f"  ▸ {codec} | {ch}ch | {br} | LANG: {lang}"
            f"{' | Atmos' if atmos else ''}"
        )

        if score > best_audio_score:
            best_audio_score = score
            audio_priority_score = base * 10 + bonus

    print(f"\n🎧 Audio Score: {best_audio_score} / 7")

    # ====================
    # VERDICT
    # ====================
    if video_score == 6:
        verdict = "REFERENCE QUALITY" if best_audio_score >= 6 else "EXCELLENT"
    elif video_score == 5 and best_audio_score >= 5:
        verdict = "EXCELLENT"
    elif video_score == 4:
        verdict = "GOOD" if best_audio_score >= 4 else "MEDIUM"
    else:
        verdict = "MEDIUM"

    # 🔒 HARD GATE: SDR CANNOT BE REFERENCE
    if verdict == "REFERENCE QUALITY" and not is_hdr:
        verdict = "EXCELLENT"

    print(f"\n🏁 Verdict: {verdict}")
    print_separator()

    FILE_VIDEO_SCORE[str(file)] = video_score
    FILE_AUDIO_SCORE[str(file)] = audio_priority_score


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

