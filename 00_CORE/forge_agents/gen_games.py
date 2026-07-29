#!/usr/bin/env python3
"""
gen_games.py — Forge game-builder wrapper (reusable, CLAUDE.md rule #5).
Routes single-file Three.js game generation through the FREE LLM tier
(Gemini Flash direct, Groq Llama fallback — the sanctioned backups in CLAUDE.md).
The free model writes the code; Claude only orchestrates + validates by booting it.
Bypasses forge_call's router (ds2api/rtk down, groq 413 from NMP payload bloat).

Usage:
  python 00_CORE/forge_agents/gen_games.py            # build all
  python 00_CORE/forge_agents/gen_games.py speed-rush # build one slug
"""
import json, re, sys, urllib.request, urllib.error
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

def _load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = _load_env()

GAMES = [
    ("speed-rush",   "Speed Rush",   "🏎️",
     "endless 3-lane racer: ship/car locked to 3 lanes, dodge oncoming obstacles that spawn faster over time, "
     "score = distance + near-miss bonus when you pass close to an obstacle, speed ramps each wave",
     "Left/Right arrows or A/D or tap left/right half to switch lane"),
    ("spore-fighter", "Spore Fighter", "🚀",
     "top-down survival swarm: spores spawn at edges and home toward the player, auto-fire destroys them, "
     "a dash (cooldown) phases through, density escalates over time, score per spore killed, 3 lives",
     "Mouse/WASD to move, Space to dash"),
    ("crystal-orb",  "Crystal Orb",  "💎",
     "minimal timing game: a glowing ring with one lit catch-segment rotates around center, crystals fall toward "
     "the ring, rotate the lit segment to intercept each crystal, miss = lose a life, speed ramps, combo multiplier",
     "Left/Right or A/D to rotate the catch-segment, or tap left/right"),
    ("void-runner",  "Void Runner",  "🌀",
     "tunnel flyer: camera flies forward through an accelerating procedural ring tunnel, each ring has a gap, "
     "steer the craft to thread the gap, hit a wall = lose a life, score = rings passed, speed ramps continuously",
     "Mouse/Arrows/WASD to steer within the tunnel cross-section"),
    ("neon-reflex",  "Neon Reflex",  "⚡",
     "reaction grid: a grid of neon cells, random cells light up and fade after a shrinking timeout, hit lit cells "
     "before they fade for points + combo streak, missing a fade or hitting a dark cell loses a life, pace speeds up",
     "Mouse click / tap the lit cells"),
]

PROMPT = """Produce a COMPLETE, self-contained single HTML file: a polished Three.js arcade game named "{title}" {emoji}.
Three.js is loaded from CDN (https://unpkg.com/three@0.160.0/build/three.min.js).

INCLUDE these robust patterns (do not skip any):
- CDN <script> load with a guard + readable on-page error panel if Three.js fails to load
- full state machine: menu -> play -> pause -> gameover -> restart
- HUD: score + persistent BEST via localStorage wrapped in try/catch
- WebAudio synthesized SFX (NO audio files) with a mute toggle, pause on P/Esc and on blur
- particle/object pooling, requestAnimationFrame loop with delta time, responsive resize, devicePixelRatio cap
- additive neon-glow aesthetic, PROCEDURAL geometry only — NO external assets, NO images
- clean console: no 404s, no thrown errors

CORE MECHANIC: {mechanic}
CONTROLS: {controls}

HARD RULES:
- The file MUST be COMPLETE and run with ZERO errors. Do not truncate. Close every tag and brace.
- Keep it COMPACT: ~250-380 lines is ideal. Lean but fully playable.
- Output ONLY raw HTML, from <!DOCTYPE html> to </html>. NO markdown fences, NO commentary before or after.
"""

def _post(url, payload, headers):
    # Browser UA: Groq sits behind Cloudflare, which blocks the default urllib UA (error 1010).
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", **headers})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception as exc:
            logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        raise RuntimeError(f"HTTP {e.code}: {body}")

GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-flash-latest"]

def gen(prompt):
    """Free-tier generation: Groq Llama first (Gemini quota-capped), Gemini fallback."""
    errs = []
    qk = ENV.get("GROQ_API_KEY")
    if qk:
        for model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
            try:
                j = _post("https://api.groq.com/openai/v1/chat/completions",
                          {"model": model, "max_tokens": 8000, "temperature": 0.6,
                           "messages": [{"role": "user", "content": prompt}]},
                          {"Authorization": "Bearer " + qk})
                return j["choices"][0]["message"]["content"]
            except Exception as e:
                errs.append(f"groq/{model}: {str(e)[:180]}")
    gk = ENV.get("GOOGLE_AI_STUDIO_KEY")
    if gk:
        for model in GEMINI_MODELS:
            try:
                url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                       f"{model}:generateContent?key=" + gk)
                j = _post(url, {"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.6}}, {})
                return j["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                errs.append(f"gemini/{model}: {str(e)[:180]}")
    raise RuntimeError(" || ".join(errs) or "no free key configured")

def strip_fences(s):
    s = (s or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\n", "", s)
    s = re.sub(r"\n```$", "", s)
    i = s.lower().find("<!doctype")
    j = s.lower().rfind("</html>")
    if i != -1 and j != -1:
        s = s[i:j + len("</html>")]
    return s.strip()

def build(slug, title, emoji, mechanic, controls):
    prompt = PROMPT.format(title=title, emoji=emoji, mechanic=mechanic, controls=controls)
    html = strip_fences(gen(prompt))
    ok = html.lower().startswith("<!doctype") and "</html>" in html.lower() and len(html) > 1500
    if ok:
        d = ROOT / "mvp_output" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(html, encoding="utf-8")
    return {"slug": slug, "ok": ok, "bytes": len(html)}

def main():
    want = set(sys.argv[1:])
    report = []
    for g in GAMES:
        if want and g[0] not in want:
            continue
        try:
            report.append(build(*g))
        except Exception as e:
            report.append({"slug": g[0], "ok": False, "error": str(e)[:700]})
    (ROOT / "mvp_output" / "_gen_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("RESULT:" + json.dumps(report))

if __name__ == "__main__":
    main()
