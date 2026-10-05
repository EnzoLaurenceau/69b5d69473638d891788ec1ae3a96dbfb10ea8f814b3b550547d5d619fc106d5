"""
qc.py — Contrôle qualité automatique d'un Reel exporté
======================================================
Vérifie : specs Instagram (1080x1920, 30 fps, H.264 High, yuv420p, bt709,
AAC 48 kHz stéréo), frames noires, loudness intégrée (≈ -14 LUFS), true peak
(≤ -1 dBTP), clipping, continuité de boucle (dernière vs première frame),
texte dans les safe zones Instagram (haut 14 %, bas 35 %, côtés 6 %),
hook (< 1 s), densité de coupes. Écrit <name>_qc.json + <name>_safezone.jpg.

Usage :
    python qc.py out_dir/NAME.mp4 [--ass out_dir/NAME.ass --fonts fonts_dir]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 1080, 1920
SAFE = {"x0": int(0.06 * W), "x1": int(0.94 * W), "y0": int(0.14 * H), "y1": int(0.65 * H)}


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout + p.stderr


def probe(mp4: str) -> dict:
    out = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", mp4]))
    v = next(s for s in out["streams"] if s["codec_type"] == "video")
    a = next(s for s in out["streams"] if s["codec_type"] == "audio")
    return {"w": v["width"], "h": v["height"], "fps": v["r_frame_rate"], "vcodec": v["codec_name"],
            "profile": v.get("profile"), "pix_fmt": v["pix_fmt"], "color": v.get("color_space"),
            "acodec": a["codec_name"], "sr": int(a["sample_rate"]), "ch": a["channels"],
            "duration": float(out["format"]["duration"]), "mbps": round(int(out["format"]["bit_rate"]) / 1e6, 1),
            "size_mb": round(int(out["format"]["size"]) / 1e6, 1)}


def frames_gray(mp4: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp4, "-vf", "scale=108:192,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 192, 108).astype(np.float32)


def loudness(mp4: str) -> dict:
    txt = run(["ffmpeg", "-nostats", "-i", mp4, "-af", "ebur128=peak=true", "-f", "null", "-"])
    summ = txt[txt.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summ).group(1))
    tp = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ).group(1))
    st = run(["ffmpeg", "-i", mp4, "-af", "astats=measure_overall=Peak_level+Number_of_samples", "-f", "null", "-"])
    pk = max(float(x) for x in re.findall(r"Peak level dB:\s+(-?[\d.]+|-inf)", st) if x != "-inf")
    return {"lufs_i": i, "true_peak_dbtp": tp, "sample_peak_db": pk}


def text_bbox(ass: str, fonts: str, t: float) -> tuple[int, int, int, int] | None:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:d={t + 0.1}:r=30",
                          "-vf", f"subtitles=filename={ass}:fontsdir={fonts},format=gray", "-ss", str(t),
                          "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    img = np.frombuffer(raw, np.uint8).reshape(H, W)
    ys, xs = np.nonzero(img > 140)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


def main() -> None:
    mp4 = sys.argv[1]
    name = Path(mp4).stem
    out = Path(mp4).parent
    pr = probe(mp4)
    g = frames_gray(mp4)
    luma = g.mean((1, 2))
    diffs = np.abs(np.diff(g, axis=0)).mean((1, 2))
    seam = float(np.abs(g[-1] - g[0]).mean())
    markers = json.loads((out / f"{name}_markers.json").read_text())
    cuts = markers["cuts"]
    res = {"name": name, "probe": pr, "audio": loudness(mp4),
           "black_frames": int((luma < 18).sum()), "min_luma": round(float(luma.min()), 1),
           "loop_seam_diff": round(seam, 2), "median_frame_diff": round(float(np.median(diffs)), 2),
           "p90_frame_diff": round(float(np.percentile(diffs, 90)), 2),
           "first_cut_s": cuts[1] if len(cuts) > 1 else None, "loop": markers.get("loop", "seamless"),
           "cuts_per_s": round((len(cuts) - 1) / markers["duration"], 2), "text": []}
    if "--ass" in sys.argv:
        ass, fonts = sys.argv[sys.argv.index("--ass") + 1], sys.argv[sys.argv.index("--fonts") + 1]
        for m in re.finditer(r"Dialogue: 1,(\S+?),(\S+?),", Path(ass).read_text()):
            s, e = (sum(float(x) * k for x, k in zip(v.split(":"), (3600, 60, 1))) for v in m.groups())
            bb = text_bbox(ass, fonts, min((s + e) / 2 + 0.4, e - 0.2))  # hors fondu de sortie
            ok = bb is not None and bb[0] >= SAFE["x0"] and bb[2] <= SAFE["x1"] and bb[1] >= SAFE["y0"] and bb[3] <= SAFE["y1"]
            res["text"].append({"start": s, "end": e, "bbox": bb, "in_safe_zone": ok})
        t = res["text"][0]["start"] + 1.0 if res["text"] else 1.0
        x0, y0, x1, y1 = SAFE.values()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", mp4, "-frames:v", "1", "-vf",
                        f"drawbox=x={x0}:y={y0}:w={x1 - x0}:h={y1 - y0}:color=cyan@0.9:t=4,"
                        f"drawbox=x=0:y={y1}:w={W}:h={H - y1}:color=red@0.25:t=fill,"
                        f"drawbox=x=0:y=0:w={W}:h={y0}:color=red@0.25:t=fill,scale=540:960",
                        str(out / f"{name}_safezone.jpg")], check=True)
    a = res["audio"]
    res["checks"] = {
        "vertical_1080x1920": pr["w"] == W and pr["h"] == H, "fps_30": pr["fps"] == "30/1",
        "h264_high_yuv420p": pr["vcodec"] == "h264" and pr["profile"] == "High" and pr["pix_fmt"] == "yuv420p",
        "bt709": pr["color"] == "bt709", "aac_48k_stereo": pr["acodec"] == "aac" and pr["sr"] == 48000 and pr["ch"] == 2,
        "no_black_frames": res["black_frames"] == 0, "loudness_target_lufs": abs(a["lufs_i"] - markers.get("lufs", -14.0)) <= 1.0,
        "true_peak_le_-1": a["true_peak_dbtp"] <= -0.9, "no_clipping": a["sample_peak_db"] < -0.5,
        "hook_lt_1s": (res["first_cut_s"] is not None and res["first_cut_s"] <= 1.0)
                      or (bool(res["text"]) and min(x["start"] for x in res["text"]) <= 0.5),
        "loop_seam_smooth": seam <= res["p90_frame_diff"] * 1.5 if markers.get("loop", "seamless") == "seamless" else True,
        "text_in_safe_zone": all(x["in_safe_zone"] for x in res["text"]),
    }
    (out / f"{name}_qc.json").write_text(json.dumps(res, indent=1))
    bad = [k for k, v in res["checks"].items() if not v]
    print(f"{name}: {'PASS' if not bad else 'FAIL ' + str(bad)} | {pr['duration']:.2f}s {pr['mbps']}Mbps "
          f"{a['lufs_i']}LUFS TP {a['true_peak_dbtp']} seam {seam:.1f} (p90 {res['p90_frame_diff']})")


if __name__ == "__main__":
    main()
