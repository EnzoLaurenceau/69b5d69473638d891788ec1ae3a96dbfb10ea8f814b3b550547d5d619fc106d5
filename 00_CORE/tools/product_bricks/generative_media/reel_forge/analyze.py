"""
analyze.py — Analyse frame-by-frame d'un clip court (Reel/TikTok)
=================================================================
Mesure, pour CHAQUE frame : mouvement (flux optique Farneback), direction
caméra, netteté (variance Laplacien), luminance, saturation, ratio de vert,
visages (Haar frontal + profil), frames noires. Ajoute : coupes de scène
(PySceneDetect), enveloppe audio + onsets (librosa), transcription locale
(faster-whisper, optionnelle). Sortie : analysis.json + analysis.png.

Usage :
    python analyze.py clip.mp4 out_dir [--no-asr]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


def frame_metrics(path: str) -> tuple[list[dict], float]:
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    data = cv2.data.haarcascades
    front = cv2.CascadeClassifier(data + "haarcascade_frontalface_default.xml")
    prof = cv2.CascadeClassifier(data + "haarcascade_profileface.xml")
    prev, rows, i = None, [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (270, 480))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mag, ang, dx, dy = 0.0, 0.0, 0.0, 0.0
        if prev is not None:
            flow = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            m, a = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            mag = float(m.mean())
            dx, dy = float(flow[..., 0].mean()), float(flow[..., 1].mean())
            ang = float(np.degrees(np.arctan2(dy, dx)))
        prev = gray
        faces = list(front.detectMultiScale(gray, 1.15, 5, minSize=(40, 40)))
        faces += list(prof.detectMultiScale(gray, 1.15, 5, minSize=(40, 40)))
        h = hsv[..., 0]
        green = float(((h > 35) & (h < 85) & (hsv[..., 1] > 60)).mean())
        rows.append({
            "i": i, "t": round(i / fps, 3),
            "motion": round(mag, 3), "dx": round(dx, 3), "dy": round(dy, 3), "dir_deg": round(ang, 1),
            "sharp": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1),
            "luma": round(float(gray.mean()), 1),
            "sat": round(float(hsv[..., 1].mean()), 1),
            "green": round(green, 3),
            "faces": len(faces),
            "face_area": round(max([w * h_ for (_, _, w, h_) in faces], default=0) / (270 * 480), 3),
            "black": bool(gray.mean() < 25),
        })
        i += 1
    return rows, fps


def scenes(path: str) -> list[float]:
    from scenedetect import ContentDetector, detect
    return [round(s[0].get_seconds(), 3) for s in detect(path, ContentDetector(threshold=22))]


def audio(path: str, out: Path) -> dict:
    import librosa
    wav = out / "audio16k.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000", str(wav)], check=True)
    y, sr = librosa.load(str(wav), sr=16000)
    hop = 16000 // 30
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    on = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop, units="time")
    return {"rms_db": [round(float(v), 1) for v in librosa.amplitude_to_db(rms + 1e-9)],
            "onsets": [round(float(t), 3) for t in on], "peak_db": round(float(20 * np.log10(np.abs(y).max() + 1e-9)), 2)}


def transcribe(path: str) -> list[dict]:
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(path, word_timestamps=True, vad_filter=False)
    return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
             "words": [{"w": w.word, "s": round(w.start, 2), "e": round(w.end, 2)} for w in (s.words or [])]}
            for s in segs]


def plot(rows: list[dict], cuts: list[float], aud: dict, out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = [r["t"] for r in rows]
    fig, ax = plt.subplots(5, 1, figsize=(14, 10), sharex=True)
    for a, key, lab in zip(ax, ["motion", "sharp", "face_area", "green"], ["mouvement", "netteté", "visage (aire)", "vert"]):
        a.plot(t, [r[key] for r in rows], lw=1.2)
        a.set_ylabel(lab)
        for c in cuts:
            a.axvline(c, color="r", ls="--", lw=0.8)
    ax[4].plot([i / 30 for i in range(len(aud["rms_db"]))], aud["rms_db"], lw=1)
    for o in aud["onsets"]:
        ax[4].axvline(o, color="g", lw=0.5)
    ax[4].set_ylabel("audio dB")
    ax[4].set_xlabel("secondes")
    ax[4].set_xticks(np.arange(0, t[-1] + 0.5, 0.5))
    fig.tight_layout()
    fig.savefig(out / "analysis.png", dpi=90)


def main() -> None:
    src, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rows, fps = frame_metrics(src)
    cuts = scenes(src)
    aud = audio(src, out)
    asr = [] if "--no-asr" in sys.argv else transcribe(src)
    plot(rows, cuts, aud, out)
    (out / "analysis.json").write_text(json.dumps(
        {"fps": fps, "frames": rows, "scene_cuts": cuts, "audio": aud, "transcript": asr}, ensure_ascii=False))
    print(f"frames={len(rows)} cuts={cuts} onsets={len(aud['onsets'])} peak={aud['peak_db']}dBFS asr_segments={len(asr)}")


if __name__ == "__main__":
    main()
