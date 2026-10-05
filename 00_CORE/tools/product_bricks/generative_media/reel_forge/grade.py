"""
grade.py — Génère un LUT 3D (.cube) « cinematic natural » pour ffmpeg lut3d
===========================================================================
Intention : premium / naturel / légèrement contrasté. Verts contrôlés
(désaturés, tirés vers l'olive, assombris), tons chair protégés, hautes
lumières douces (shoulder), noirs propres (pas écrasés), split-tone discret
(ombres froides / hautes lumières chaudes).

Usage :
    python grade.py out.cube [--size 33]
"""
from __future__ import annotations

import sys

import numpy as np


def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rc = np.where(m & (mx == r), ((g - b) / np.where(m, d, 1)) % 6, 0)
    gc = np.where(m & (mx == g) & (mx != r), (b - r) / np.where(m, d, 1) + 2, 0)
    bc = np.where(m & (mx == b) & (mx != r) & (mx != g), (r - g) / np.where(m, d, 1) + 4, 0)
    h = (rc + gc + bc) * 60.0
    s = np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1), 0)
    return np.stack([h % 360, s, mx], -1)


def hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    h, s, v = hsv[..., 0] / 60.0, hsv[..., 1], hsv[..., 2]
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    sel = [np.stack(c, -1) for c in ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))]
    out = np.zeros(hsv.shape)
    for k in range(6):
        out[i == k] = sel[k][i == k]
    return out


def band(h: np.ndarray, center: float, width: float) -> np.ndarray:
    """Poids lisse (cosinus) autour d'une teinte, largeur = demi-largeur en degrés."""
    d = np.abs((h - center + 180) % 360 - 180)
    return np.where(d < width, 0.5 + 0.5 * np.cos(np.pi * d / width), 0.0)


def tone(x: np.ndarray, k: float = 2.6, expo: float = 1.0) -> np.ndarray:
    """Courbe filmique : noirs propres (lift léger), S douce, épaule des HL."""
    x = 0.012 + np.clip(x * expo, 0, 1) * 0.985
    s = x + 0.16 * np.sin(np.pi * (x - 0.5) * 2) / (2 * np.pi) * k  # S-curve centrée
    s = np.clip(s, 0, None)
    knee = 0.80
    hi = s > knee
    s[hi] = knee + (1 - knee) * np.tanh((s[hi] - knee) / (1 - knee) * 1.15)
    return np.clip(s, 0, 1)


LOOKS = {  # natural = premium naturel ; dark = Venkai sombre (noir/blanc/cyan, verts éteints)
    "natural": dict(k=2.6, expo=1.0, gdesat=0.46, gdark=0.20, sat=0.94,
                    shadow=(-0.010, 0.004, 0.016), high=(0.018, 0.006, -0.014)),
    "dark": dict(k=3.4, expo=0.88, gdesat=0.58, gdark=0.30, sat=0.86,
                 shadow=(-0.018, 0.010, 0.026), high=(0.004, 0.004, 0.002)),
}


def grade(rgb: np.ndarray, look: str = "natural") -> np.ndarray:
    L = LOOKS[look]
    out = tone(rgb, L["k"], L["expo"])
    hsv = rgb_to_hsv(out)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    g = band(h, 95, 60)             # verts / feuillage (herbe ≈ 75–90°)
    skin = band(h, 25, 22)          # tons chair
    h = h + 4 * g                   # verts → plus profonds (anti « citron vert »)
    s = s * (1 - L["gdesat"] * g)    # verts désaturés
    v = v * (1 - L["gdark"] * g * s)  # verts plus denses
    s = s * (L["sat"] + (1 - L["sat"]) * skin) * (1 + 0.04 * skin)
    out = hsv_to_rgb(np.stack([h % 360, np.clip(s, 0, 1), np.clip(v, 0, 1)], -1))
    lum = (out @ np.array([0.2126, 0.7152, 0.0722]))[..., None]
    shadow = np.clip(1 - lum / 0.45, 0, 1) ** 1.5
    high = np.clip((lum - 0.55) / 0.45, 0, 1)
    out = out + shadow * np.array(L["shadow"]) + high * np.array(L["high"])
    return np.clip(out, 0, 1)


def write_cube(path: str, size: int = 33, look: str = "natural") -> None:
    ax = np.linspace(0, 1, size)
    b, g, r = np.meshgrid(ax, ax, ax, indexing="ij")  # r varie le plus vite
    rgb = np.stack([r, g, b], -1).reshape(-1, 3)
    res = grade(rgb, look)
    with open(path, "w") as f:
        f.write(f'TITLE "reel_forge cinematic natural"\nLUT_3D_SIZE {size}\n')
        f.writelines(f"{x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in res)


if __name__ == "__main__":
    size = int(sys.argv[sys.argv.index("--size") + 1]) if "--size" in sys.argv else 33
    look = sys.argv[sys.argv.index("--look") + 1] if "--look" in sys.argv else "natural"
    write_cube(sys.argv[1], size, look)
    print(f"cube → {sys.argv[1]} ({size}³)")
