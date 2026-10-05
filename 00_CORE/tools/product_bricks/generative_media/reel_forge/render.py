"""
render.py — EDL JSON → Reel MP4 prêt Instagram
==============================================
Time-remap par segment (vitesse constante ou speed ramp), slow-mo par
interpolation de flux optique (DIS bidirectionnel), motion blur synthétique
(obturateur 180°) sur les accélérations, micro-zooms, camera shake d'impact,
light leak, flash, étalonnage LUT 3D, grain luma, vignette, texte cinétique
(ASS/libass), sound design procédural + audio d'origine remappé, loudness
-14 LUFS / -1 dBTP, export H.264 High 1080x1920 30 fps bt709 + AAC 48 kHz.

Usage :
    python render.py edl.json src.mp4 out_dir --fonts fonts_dir
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import sfx  # noqa: E402
from grade import write_cube  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, sfx.SR


# ---------------------------------------------------------------- vidéo source
def load_video(path: str) -> list[np.ndarray]:
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=in_color_matrix=bt709:in_range=tv",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
    return [arr[i] for i in range(len(arr))]


class Source:
    """Accès temporel continu : interpolation flux optique (<1x) ou motion blur (>1.2x)."""

    def __init__(self, frames: list[np.ndarray]):
        self.f, self.n = frames, len(frames)
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        self.cache: dict[int, tuple] = {}
        self.gx, self.gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))

    def _flow(self, i: int) -> tuple:
        if i not in self.cache:
            if len(self.cache) > 24:
                self.cache.pop(next(iter(self.cache)))
            g = [cv2.cvtColor(cv2.resize(self.f[k], (W // 2, H // 2), interpolation=cv2.INTER_AREA),
                              cv2.COLOR_BGR2GRAY) for k in (i, i + 1)]
            f01, f10 = self.dis.calc(g[0], g[1], None), self.dis.calc(g[1], g[0], None)
            mag = float(np.linalg.norm(f01, axis=-1).mean())
            self.cache[i] = (cv2.resize(f01, (W, H)) * 2, cv2.resize(f10, (W, H)) * 2, mag)
        return self.cache[i]

    def lin(self, x: float) -> np.ndarray:
        x = min(max(x, 0.0), self.n - 1.0)
        i = int(x)
        fr = x - i
        if i >= self.n - 1 or fr < 1e-3:
            return self.f[i].astype(np.float32)
        return self.f[i].astype(np.float32) * (1 - fr) + self.f[i + 1].astype(np.float32) * fr

    def interp(self, i: int, t: float) -> np.ndarray:
        f01, f10, mag = self._flow(i)
        if mag > 22:  # whip / flou extrême : le fondu ressemble à du motion blur
            return self.lin(i + t)
        a = cv2.remap(self.f[i], self.gx - t * f01[..., 0], self.gy - t * f01[..., 1],
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        b = cv2.remap(self.f[i + 1], self.gx - (1 - t) * f10[..., 0], self.gy - (1 - t) * f10[..., 1],
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return a.astype(np.float32) * (1 - t) + b.astype(np.float32) * t

    def at(self, s: float, v: float) -> np.ndarray:
        x = min(max(s * FPS, 0.0), self.n - 1.0)
        if v > 1.2:
            w = v * 0.5
            k = max(2, math.ceil(w * 2) + 1)
            return sum(self.lin(p) for p in np.linspace(x - w / 2, x + w / 2, k)) / k
        i, fr = int(x), x - int(x)
        if fr < 0.06 or i >= self.n - 1:
            return self.f[i].astype(np.float32)
        if fr > 0.94:
            return self.f[i + 1].astype(np.float32)
        return self.interp(i, fr)


# ---------------------------------------------------------------- timeline
def ease(kind: str, u: float, p: float = 2.4) -> float:
    if kind == "ramp_up":
        return 0.4 * u + 0.6 * u ** p
    if kind == "ramp_down":
        return 0.4 * u + 0.6 * (1 - (1 - u) ** p)
    return u


def timeline(edl: dict) -> list[dict]:
    """Une entrée par frame de sortie : source time, vitesse locale, transform."""
    out, t0 = [], 0
    for si, seg in enumerate(edl["segments"]):
        a, b = seg["src"]
        nf = round(seg["dur"] * FPS)
        z0, z1 = seg.get("zoom", [1.0, 1.0])
        for j in range(nf):
            u, u2 = j / nf, (j + 1) / nf
            k = seg.get("ease", "linear")
            s = a + (b - a) * ease(k, u)
            v = (b - a) * (ease(k, u2) - ease(k, u)) * FPS
            sm = u * u * (3 - 2 * u)
            out.append({"t": (t0 + j) / FPS, "s": s, "v": abs(v), "seg": si, "z": z0 + (z1 - z0) * sm,
                        "c": seg.get("center", [0.5, 0.5]), "rot": seg.get("rot", 0.0)})
        t0 += nf
    return out


def fx_at(edl: dict, kind: str, t: float):
    for e in edl.get("fx", []):
        if e["type"] == kind and e["t"] <= t < e["t"] + e.get("dur", 0.25):
            yield e, t - e["t"]


_LEAK = None


def leak_map() -> np.ndarray:
    global _LEAK
    if _LEAK is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        g = np.exp(-(((xx - 0.95 * W) / (0.55 * W)) ** 2 + ((yy - 0.18 * H) / (0.45 * H)) ** 2))
        _LEAK = g[..., None] * np.array([70, 150, 255], np.float32)[None, None] / 255.0
    return _LEAK


def frame(src: Source, fr: dict, edl: dict) -> np.ndarray:
    img = src.at(fr["s"], fr["v"])
    z, tx, ty = fr["z"], 0.0, 0.0
    for e, dt in fx_at(edl, "shake", fr["t"]):
        amp = e.get("amp", 10) * math.exp(-dt * 11)
        tx += amp * math.sin(2 * math.pi * 19 * dt)
        ty += amp * math.cos(2 * math.pi * 13 * dt + 0.7)
        z = max(z, 1.0 + 2.4 * e.get("amp", 10) / W)
    if abs(z - 1) > 1e-4 or tx or ty or fr["rot"]:
        cx, cy = fr["c"]
        m = cv2.getRotationMatrix2D((cx * W, cy * H), fr["rot"], z)
        m[0, 2] += tx
        m[1, 2] += ty
        img = cv2.warpAffine(img, m, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    for e, dt in fx_at(edl, "leak", fr["t"]):
        a = e.get("strength", 0.3) * math.sin(math.pi * dt / e.get("dur", 0.6)) ** 2
        img = 255 - (255 - img) * (1 - a * leak_map())
    for e, dt in fx_at(edl, "dim", fr["t"]):
        k = e.get("level", 0.45) * min(1.0, dt / max(e.get("ramp", 0.5), 1e-3))
        if e.get("ramp_out"):
            k *= min(1.0, (e.get("dur", 0.25) - dt) / e["ramp_out"])
        img = img * (1 - k)
    for e, dt in fx_at(edl, "rgbsplit", fr["t"]):
        px = int(round(e.get("px", 10) * math.exp(-dt * 18)))
        if px:
            img = img.copy()
            img[..., 2] = np.roll(img[..., 2], px, axis=1)
            img[..., 0] = np.roll(img[..., 0], -px, axis=1)
    for e, dt in fx_at(edl, "flash", fr["t"]):
        k = e.get("strength", 0.15) * math.exp(-dt * 22)
        img = img + (255 - img) * k
    return np.clip(img, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- texte
def reveal(x: dict, tag: str, target: str) -> str:
    """Sous-titres mot par mot (karaoké doux) si x["reveal"] == "words"."""
    if x.get("reveal") != "words":
        return x["text"]
    step, out, i = x.get("word_ms", 110), [], 0
    for tok in re.split(r"( |\\N)", x["text"]):
        if tok in ("", " ", "\\N"):
            out.append(tok)
            continue
        out.append(f"{{{tag}&HFF&\\t({i * step},{i * step + 160},{tag}&H{target}&)}}{tok}")
        i += 1
    return "".join(out)


def ass_file(edl: dict, path: Path) -> list[float]:
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
            "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
            "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Serif,DM Serif Display,84,&H00F4F4F4,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,5,70,70,0,1\n"
            "Style: Box,Poppins ExtraBold,96,&H00FFFFFF,&H00FFFFFF,&H10000000,&H00000000,0,0,0,0,100,100,0,0,3,20,0,5,70,70,0,1\n"
            "Style: Mark,Poppins SemiBold,50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,16,0,1,0,0,5,70,70,0,1\n"
            "Style: Sig,Inter,30,&H30F4F4F4,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,9,0,1,0,0,5,70,70,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

    def ts(t: float) -> str:
        return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"

    lines, ticks = [], []
    for x in edl.get("text", []):
        y, st = x.get("y", 1130), x.get("style", "Serif")
        if st in ("Box", "Mark"):
            hl, yel = x.get("hl_ms", 380), "&H00D4FF&"  # jaune accent (#FFD400, BGR)
            body = re.sub(r"\[\[(.+?)\]\]", lambda m: f"{{\\t({hl},{hl + 90},\\1c{yel})}}{m.group(1)}{{\\1c&HFFFFFF&}}", x["text"])
            if st == "Box":
                tags = f"\\an5\\pos(540,{y})\\fad(70,{x.get('fade_out', 110)})\\fscx86\\fscy86\\t(0,140,\\fscx100\\fscy100)"
                longest = max(len(re.sub(r"{[^}]*}|\[\[|\]\]", "", ln)) for ln in x["text"].split("\\N"))
                tags += f"\\fs{x.get('size', min(104, int(900 / (0.345 * max(longest, 1)))))}"
            else:
                tags = f"\\an5\\pos(540,{y})\\fad(300,200)\\fsp30\\t(0,900,0.5,\\fsp16)\\1a&H18&"
            lines.append(f"Dialogue: 1,{ts(x['start'])},{ts(x['end'])},{st},,0,0,0,,{{{tags}}}{body}")
            ticks.append(x["start"])
            continue
        sp0, sp1 = (14, 9) if st == "Sig" else (4, 0)
        longest = max(len(re.sub(r"{[^}]*}", "", ln)) for ln in x["text"].split("\\N"))
        size = x.get("size", min(84, int(1800 / max(longest, 1))) if st == "Serif" else None)
        fs = f"\\fs{size}" if size else ""
        anim = (f"{fs}\\an5\\move(540,{y + 14},540,{y},0,900)\\fad(280,{x.get('fade_out', 320)})"
                f"\\fsp{sp0}\\t(0,900,0.5,\\fsp{sp1})")
        shadow_txt, main_txt = reveal(x, "\\alpha", "48"), reveal(x, "\\alpha", "00")
        lines.append(f"Dialogue: 0,{ts(x['start'])},{ts(x['end'])},{st},,0,0,0,,"
                     f"{{{anim}\\1c&H000000&\\3c&H000000&\\bord5\\alpha&H48&\\blur14}}{shadow_txt}")
        lines.append(f"Dialogue: 1,{ts(x['start'])},{ts(x['end'])},{st},,0,0,0,,"
                     f"{{{anim}\\blur7\\t(0,420,\\blur0.6)}}{main_txt}")
        ticks.append(x["start"])
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return ticks


# ---------------------------------------------------------------- audio
def load_audio(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def natural_track(edl: dict, aud: np.ndarray) -> np.ndarray:
    import librosa
    parts, fade = [], int(0.012 * SR)
    for seg in edl["segments"]:
        a, b = seg["src"]
        n_out = round(seg["dur"] * FPS) * SR // FPS
        chunk = aud[int(a * SR):int(b * SR)]
        rate = (b - a) / (n_out / SR)
        if len(chunk) < 256:
            y = np.zeros((n_out, 2), np.float32)
        elif rate < 0.93:
            y = np.stack([librosa.effects.time_stretch(np.ascontiguousarray(chunk[:, c]), rate=rate) for c in range(2)], -1)
            y = np.pad(y[:n_out], ((0, max(0, n_out - len(y))), (0, 0)), mode="edge")
            y = sfx.lowpass(y, 1100) * 10 ** (-5 / 20)
        else:
            idx = np.linspace(0, len(chunk) - 1, n_out)
            y = np.stack([np.interp(idx, np.arange(len(chunk)), chunk[:, c]) for c in range(2)], -1)
            if rate > 1.08:
                y *= 10 ** (-6 / 20)
        y = np.asarray(y, np.float32)
        ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
        y[:fade] *= ramp
        y[-fade:] *= ramp[::-1]
        parts.append(y)
    out = np.concatenate(parts)
    return sfx.highpass(out, 100) * 10 ** (edl.get("audio", {}).get("natural_db", -9) / 20)


def place(buf: np.ndarray, x: np.ndarray, start: float, gain_db: float) -> None:
    """Ajoute x à buf à partir de start (s), avec wrap circulaire → boucle sonore sans couture."""
    idx = (int(round(start * SR)) + np.arange(len(x))) % len(buf)
    np.add.at(buf, idx, x * 10 ** (gain_db / 20))


def limiter(x: np.ndarray, ceil_db: float = -2.0) -> np.ndarray:
    """Limiteur true-peak : détection suréchantillonnée x4, lookahead lissé (pas de saut de gain)."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    from scipy.signal import resample_poly
    c = 10 ** (ceil_db / 20)
    tp = np.abs(resample_poly(x, 4, 1, axis=0)).max(1)[: len(x) * 4].reshape(-1, 4).max(1)
    g = np.minimum(1.0, c / np.maximum(tp, 1e-9))
    la = int(0.003 * SR)
    g = uniform_filter1d(minimum_filter1d(g, 2 * la + 1), la + 1)
    rel = math.exp(-1 / (0.08 * SR))
    for i in range(1, len(g)):
        g[i] = min(g[i], 1 - (1 - g[i - 1]) * rel)
    return x * g[:, None]


def mix(edl: dict, src_audio: np.ndarray, total: float, ticks: list[float]) -> np.ndarray:
    import pyloudnorm as pyln
    n = int(round(total * SR))
    nat = natural_track(edl, src_audio)[:n]
    bus = np.zeros((n, 2), np.float32)
    bus[: len(nat)] += nat
    cfg = edl.get("audio", {})
    place(bus, sfx.wind(total + 0.6), -0.3, cfg.get("wind_db", -31))  # chevauche la couture de boucle
    for e in edl.get("fx", []):
        k, g = e["type"], e.get("gain_db", None)
        if k == "whoosh":
            d = e.get("dur", 0.45)
            place(bus, sfx.reverb(sfx.whoosh(d, e.get("dir", "R")), 0.7, 0.18), e["t"] - 0.62 * d, g or -13)
        elif k == "hit":
            place(bus, sfx.reverb(sfx.sub_hit(), 1.4, 0.2), e["t"], g or -9)
        elif k == "riser":
            d = e.get("dur", 2.0)
            place(bus, sfx.riser(d), e["t"] - d, g or -17)
        elif k == "digital":
            place(bus, sfx.digital(e.get("dur", 0.07)), e["t"], g or -24)
        elif k == "leaves":
            place(bus, sfx.leaves(e.get("dur", 1.0)), e["t"], g or -26)
    cap = cfg.get("caption_sfx", "tick")
    for t in ticks:
        if cap == "tick":
            place(bus, sfx.tick(), t, -30)
        elif cap == "digital":
            place(bus, sfx.digital(), t, -27)
    bus = sfx.highpass(bus, 28).astype(np.float32)
    meter = pyln.Meter(SR)
    for _ in range(3):
        bus = bus * 10 ** ((cfg.get("lufs", -14.0) - meter.integrated_loudness(bus)) / 20)
        bus = limiter(bus)
    return bus.astype(np.float32)


# ---------------------------------------------------------------- export
def render(edl_path: str, src_path: str, out_dir: str, fonts: str) -> Path:
    import soundfile as sf
    edl = json.loads(Path(edl_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = edl["name"]
    tl = timeline(edl)
    total = len(tl) / FPS
    for x in edl.get("text", []):
        x["text"] = x["text"].replace("{DUR}", str(round(total)))
    cube, ass = out / "grade.cube", out / f"{name}.ass"
    write_cube(str(cube), look=edl.get("look", "natural"))
    ticks = ass_file(edl, ass)
    wav = out / f"{name}.wav"
    sf.write(wav, mix(edl, load_audio(src_path), total, ticks), SR, subtype="PCM_24")
    mp4 = out / f"{name}.mp4"
    vf = (f"lut3d=file={cube}:interp=tetrahedral,vignette=angle={edl.get('vignette', 0.45)},"
          f"scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,noise=c0s=5:c0f=t+u,"
          f"subtitles=filename={ass}:fontsdir={fonts}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(wav), "-vf", vf, "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-maxrate", "20M", "-bufsize", "40M", "-profile:v", "high", "-level", "4.2",
           "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-x264-params", "keyint=60:min-keyint=30", "-c:a", "aac", "-b:a", "320k",
           "-ar", "48000", "-movflags", "+faststart", "-shortest", str(mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    src = Source(load_video(src_path))
    for fr in tl:
        proc.stdin.write(frame(src, fr, edl).tobytes())
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError("ffmpeg encode failed")
    beats = 60 / edl.get("bpm", 120)
    cuts, acc = [], 0
    for seg in edl["segments"]:
        cuts.append(round(acc / FPS, 3))
        acc += round(seg["dur"] * FPS)
    (out / f"{name}_markers.json").write_text(json.dumps({
        "duration": total, "bpm": edl.get("bpm", 120), "loop": edl.get("loop", "seamless"),
        "lufs": edl.get("audio", {}).get("lufs", -14.0),
        "beats": [round(i * beats, 3) for i in range(int(total / beats) + 1)],
        "cuts": cuts, "segments": [{"out": c, "src": s["src"], "label": s.get("label", "")}
                                   for c, s in zip(cuts, edl["segments"])]}, indent=1))
    if "cover" in edl:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(edl["cover"]), "-i", str(mp4), "-frames:v", "1",
                        "-q:v", "2", str(out / f"{name}_cover.jpg")], check=True)
    print(f"{name}: {total:.2f}s → {mp4}")
    return mp4


if __name__ == "__main__":
    fonts = sys.argv[sys.argv.index("--fonts") + 1] if "--fonts" in sys.argv else "."
    render(sys.argv[1], sys.argv[2], sys.argv[3], fonts)
