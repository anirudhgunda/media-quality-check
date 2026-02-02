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


# ---------------- VIDEO HELPERS ---------------- #

def detect_dolby_vision(video_stream):
    for sd in video_stream.get("side_data_list", []):
        sdt = (sd.get("side_data_type") or "").lower()
        if "dovi" in sdt or "dolby vision" in sdt:
            return True
    tag = (video_stream.get("codec_tag_string") or "").lower()
    return tag in ("dvh1", "dvhe")


def get_video_bitrate_mbps(v, fmt):
    br = v.get("bit_rate")
    if br:
        return int(br) / 1_000_000

    size = float(fmt.get("size", 0))
    duration = float(fmt.get("duration", 1))
    return (size * 8) / duration / 1_000_000


def compute_video_score(v, fmt, is_hdr, is_dv):
    width = v.get("width", 0)
    vbps = get_video_bitrate_mbps(v, fmt)

    score = 0.0
    verdict = "MEDIUM"

    if width >= 3840:
        if is_dv or is_hdr:
            if vbps >= 15:
                score = 5.0
                verdict = "REFERENCE QUALITY"
            elif vbps >= 12:
                score = 4.5
                verdict = "EXCELLENT"
            else:
                score = 4.0
                verdict = "GOOD"
        else:
            if vbps >= 20:
                score = 4.5
                verdict = "EXCELLENT"
            else:
                score = 4.0
                verdict = "GOOD"

    elif width >= 1920:
        if vbps >= 30:
            score = 4.5
            verdict = "EXCELLENT"
        elif vbps >= 20:
            score = 4.0
            verdict = "GOOD"
        else:
            score = 3.5
            verdict = "MEDIUM"

    elif width >= 1280:
        score = 3.0
        verdict = "MEDIUM"

    else:
        score = 2.0
        verdict = "LOW"

    return score, vbps, verdict


# ---------------- AUDIO HELPERS ---------------- #

def detect_object_audio(a):
    haystack = " ".join([
        a.get("codec_name", ""),
        a.get("codec_long_name", ""),
        a.get("profile", ""),
        " ".join(str(v) for v in a.get("tags", {}).values())
    ]).lower()

    return any(k in haystack for k in (
        "atmos",
        "dts:x",
        "dtsx",
        "dts x",
        "auro",
        "auro-3d",
        "mpeg-h",
        "3d audio"
    )), haystack  # return both boolean and string for type detection


def compute_audio_score(streams):
    best = 0.0

    for a in streams:
        if a.get("codec_type") != "audio":
            continue

        codec = a.get("codec_name", "")
        ch = a.get("channels", 0)
        profile = (a.get("profile") or "").lower()

        raw_br = a.get("bit_rate") or a.get("tags", {}).get("BPS")
        br_kbps = int(raw_br) / 1000 if raw_br else 0

        is_object, haystack = detect_object_audio(a)
        is_lossless = (
            codec == "truehd" or
            (codec.startswith("dts") and "hd" in profile)
        )

        # -------- Base score (codec + bitrate) -------- #

        if is_lossless:
            score = 5.0

        elif codec == "eac3":
            if br_kbps >= 640:
                score = 4.6
            elif br_kbps >= 448:
                score = 4.2
            elif br_kbps >= 384:
                score = 3.8
            elif br_kbps >= 256:
                score = 3.3
            else:
                score = 2.4

        elif codec == "ac3":
            if br_kbps >= 640:
                score = 3.8
            elif br_kbps >= 448:
                score = 3.4
            else:
                score = 3.0

        elif codec == "aac":
            if ch >= 6 and br_kbps >= 384:
                score = 3.0
            elif ch >= 2:
                score = 2.4
            else:
                score = 2.0

        else:
            score = 2.0

        # -------- Channel bonus (small) -------- #

        if ch >= 8:
            score += 0.2
        elif ch >= 6:
            score += 0.1

        # -------- Object audio bonus (conditional on bitrate) -------- #

        if is_object:
            if is_lossless:
                pass
            elif codec == "eac3" and br_kbps >= 448:
                score += 0.15
            elif codec.startswith("dts") and br_kbps >= 1500:
                score += 0.15

        best = max(best, min(score, 5.0))

    return best


# ---------------- ANALYSIS ---------------- #

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

    # --- Video Streams ---
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

        vbps = get_video_bitrate_mbps(v, fmt)

        print(
            f"  ▸ {v.get('codec_name')} | {v.get('width')}x{v.get('height')} | "
            f"{bitdepth} | {hdr_label} | {vbps:.2f} Mbps"
        )

    best_video = max(video_streams, key=lambda x: x.get("width", 0))
    video_score, vbps, video_verdict = compute_video_score(best_video, fmt, is_hdr, is_dv)

    # --- Audio Streams ---
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    print("\n🔊 Audio Streams:")
    for a in audio_streams:
        codec = a.get("codec_name", "")
        ch = a.get("channels", 0)
        lang = a.get("tags", {}).get("language", "und")
        raw_br = a.get("bit_rate") or a.get("tags", {}).get("BPS")
        br = f"{int(int(raw_br)/1000)} kbps" if raw_br else "NA"

        is_object, haystack = detect_object_audio(a)
        obj_type = ""
        if is_object:
            if "atmos" in haystack:
                obj_type = "Atmos"
            elif "dts:x" in haystack or "dtsx" in haystack or "dts x" in haystack:
                obj_type = "DTS:X"
            elif "auro" in haystack or "auro-3d" in haystack:
                obj_type = "Auro-3D"
            elif "mpeg-h" in haystack or "3d audio" in haystack:
                obj_type = "MPEG-H"

        obj_str = f" | {obj_type}" if obj_type else ""
        print(f"  ▸ {codec} | {ch}ch | {br} | LANG: {lang}{obj_str}")

    audio_score = compute_audio_score(audio_streams)

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
        best_file = max(
            FILE_MEDIA_SCORE.items(),
            key=lambda x: (x[1][0], x[1][1])
        )[0]
        display = best_file if len(best_file) <= 100 else "..." + best_file[-97:]
        print(f"✅ Preferred File: {display}")
        print_separator()


if __name__ == "__main__":
    main()
