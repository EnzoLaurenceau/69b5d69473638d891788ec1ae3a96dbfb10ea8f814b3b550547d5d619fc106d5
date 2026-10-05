"""
sfx.py — Sound design procédural (aucun sample tiers → zéro problème de droits)
==============================================================================
Tous les sons sont synthétisés (bruit filtré, sinus glissés, enveloppes) en
stéréo 48 kHz float32 :
  whoosh(dur, direction)  — passage d'air filtré + pan, pour whip pans
  sub_hit()               — impact grave discret (sub 70→38 Hz + transient)
  riser(dur)              — montée bruit + glissando, coupée sur le payoff
  tick()                  — micro-SFX d'apparition de texte
  leaves(dur)             — froissement de feuilles (granulaire)
  wind(dur)               — lit d'ambiance vent/forêt
  reverb(x)               — réverbération synthétique (IR bruit décroissant)
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt, stft, istft

SR = 48000
_rng = np.random.default_rng(7)


def _env(n: int, attack: float, release: float, curve: float = 2.0) -> np.ndarray:
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a) ** curve
    e[-r:] *= np.linspace(1, 0, r) ** curve
    return e


def _pan(mono: np.ndarray, pan: np.ndarray | float) -> np.ndarray:
    p = (np.asarray(pan) + 1) * np.pi / 4  # -1 gauche … +1 droite (equal power)
    return np.stack([mono * np.cos(p), mono * np.sin(p)], -1).astype(np.float32)


def _swept_band(noise: np.ndarray, f_track: np.ndarray, q: float) -> np.ndarray:
    """Bande passante dont le centre suit f_track (Hz, une valeur par sample) via STFT."""
    f, t, Z = stft(noise, SR, nperseg=1024, noverlap=768)
    fc = np.interp(t * SR, np.arange(len(f_track)), f_track)
    mask = np.exp(-0.5 * (np.log2((f[:, None] + 1) / fc[None, :]) * q) ** 2)
    _, y = istft(Z * mask, SR, nperseg=1024, noverlap=768)
    return y[: len(noise)]


def lowpass(x: np.ndarray, hz: float, order: int = 4) -> np.ndarray:
    return sosfilt(butter(order, hz, "low", fs=SR, output="sos"), x, axis=0)


def highpass(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, hz, "high", fs=SR, output="sos"), x, axis=0)


def whoosh(dur: float = 0.45, direction: str = "R", peak: float = 0.62) -> np.ndarray:
    n = int(dur * SR)
    u = np.linspace(0, 1, n)
    shape = np.where(u < peak, (u / peak) ** 2.2, ((1 - u) / (1 - peak)) ** 1.4)
    f_track = 350 + 2600 * shape
    y = _swept_band(_rng.standard_normal(n), f_track, 1.6) * shape
    y += 0.25 * _swept_band(_rng.standard_normal(n), f_track * 0.45, 2.5) * shape
    pan = np.linspace(-0.8, 0.8, n) if direction == "R" else np.linspace(0.8, -0.8, n)
    return _pan(y / (np.abs(y).max() + 1e-9), pan)


def sub_hit(dur: float = 0.9) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 38 + 32 * np.exp(-t * 18)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.2)
    click = highpass(_rng.standard_normal(n), 1800) * np.exp(-t * 160) * 0.35
    y = np.tanh(1.6 * (body + click)) / np.tanh(1.6)
    return _pan(y * _env(n, 0.002, 0.08), 0.0)


def riser(dur: float = 2.0) -> np.ndarray:
    n = int(dur * SR)
    u = np.linspace(0, 1, n)
    noise = _swept_band(_rng.standard_normal(n), 500 + 5500 * u ** 2, 1.2)
    tone_f = 180 * 2 ** (u * 2.3)
    tone_ = np.sin(2 * np.pi * np.cumsum(tone_f) / SR) * 0.35 + np.sin(2 * np.pi * np.cumsum(tone_f * 1.5) / SR) * 0.15
    y = (noise / (np.abs(noise).max() + 1e-9) + tone_) * u ** 2.6
    st = _pan(y, 0.0)
    st[:, 1] = np.roll(st[:, 1], int(0.011 * SR))  # léger élargissement stéréo
    return st * _env(n, 0.01, 0.006, 1.0)[:, None]


def tick() -> np.ndarray:
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 90) + highpass(_rng.standard_normal(n), 4000) * np.exp(-t * 220) * 0.4
    return _pan(y * 0.6, 0.0)


def digital(dur: float = 0.07) -> np.ndarray:
    """Micro texture numérique : blip carré bit-crushé (accent mot-clé / glitch)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    sq = np.sign(np.sin(2 * np.pi * (1800 - 900 * t / dur) * t))
    crushed = np.round((sq * 0.6 + _rng.standard_normal(n) * 0.25) * 6) / 6
    y = crushed * np.exp(-t * 45)
    st = _pan(y, 0.0)
    st[:, 1] = np.roll(st[:, 1], int(0.004 * SR))
    return st


def leaves(dur: float) -> np.ndarray:
    n = int(dur * SR)
    y = np.zeros(n)
    for _ in range(int(dur * 40)):
        L = int(_rng.uniform(0.01, 0.05) * SR)
        p = int(_rng.uniform(0, max(1, n - L)))
        y[p:p + L] += _rng.standard_normal(L) * np.hanning(L) * _rng.uniform(0.2, 1)
    y = highpass(lowpass(y, 9000), 1800)
    return _pan(y / (np.abs(y).max() + 1e-9), _rng.uniform(-0.5, 0.5)) * _env(n, 0.05, 0.1, 1)[:, None]


def wind(dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = []
    for ph in (0.0, 1.7):
        brown = np.cumsum(_rng.standard_normal(n))
        brown = highpass(brown - brown.mean(), 40)
        lfo = 0.65 + 0.35 * np.sin(2 * np.pi * 0.23 * t + ph) * np.sin(2 * np.pi * 0.071 * t + 2 * ph)
        gust = _swept_band(_rng.standard_normal(n), 500 + 300 * lfo, 1.0) * 0.4
        ch = lowpass(brown, 520) / (np.abs(brown).max() + 1e-9) * 6 + gust
        out.append(ch * lfo)
    y = np.stack(out, -1)
    return (y / (np.abs(y).max() + 1e-9) * _env(n, 0.3, 0.3, 1)[:, None]).astype(np.float32)


def reverb(x: np.ndarray, decay: float = 1.1, wet: float = 0.22) -> np.ndarray:
    n = int(decay * SR)
    t = np.arange(n) / SR
    ir = np.stack([_rng.standard_normal(n), _rng.standard_normal(n)], -1) * np.exp(-t * 6.9 / decay)[:, None]
    ir = lowpass(ir, 6000)
    ir /= np.sqrt((ir ** 2).sum(0))
    tail = np.stack([fftconvolve(x[:, c], ir[:, c]) for c in range(2)], -1)
    out = np.zeros_like(tail)
    out[: len(x)] = x * (1 - wet)
    return (out + tail * wet).astype(np.float32)
