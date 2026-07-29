"""
video_rag.py — Wrapper Video-RAG (P47Parzival/Video-RAG)
=========================================================
RAG local sur vidéos : Whisper (transcript) → embeddings HF (all-MiniLM-L6-v2)
→ Chroma (vector store) → query → réponse Gemini + extraction de frames aux
timestamps pertinents.

Cas d'usage Forge :
  - Indexer les vidéos preuve hôtel (chambres) → recherche sémantique
    « chambre avec vue mer », « suite jacuzzi » → vidéo + frame correspondante.
  - Le bot répond avec la preuve vidéo de la chambre demandée par le client.

DO NOT INVENT : on appelle le repo, on ne réécrit pas la pipeline.
status=planned : deps lourdes (whisper, torch, chromadb, ffmpeg). ensure() les
installe au 1er besoin (YAGNI). Gemini : clé GOOGLE_API_KEY.

Usage :
    from tools.research import video_rag
    video_rag.ensure()                                  # clone + deps (1re fois)
    video_rag.index("Video pub preuve/IMG_3450.MP4")    # transcript+frames+index
    res = video_rag.query("IMG_3450.MP4", "chambre avec vue mer")
    # res = {"answer": "...", "frames": ["...jpg", ...]}
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/P47Parzival/Video-RAG"
_CACHE = Path(__file__).resolve().parents[1] / "cache" / "video-rag"


def ensure() -> Path:
    """Clone le repo + installe les deps si absent. Idempotent. Retourne le chemin."""
    if not _CACHE.exists():
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", REPO, str(_CACHE)], check=True)
        req = _CACHE / "requirements.txt"
        if req.exists():
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)], check=True)
    return _CACHE


def _import_functions():
    """Importe functions.py du repo cloné (lazy, après ensure())."""
    ensure()
    if str(_CACHE) not in sys.path:
        sys.path.insert(0, str(_CACHE))
    import functions  # type: ignore
    return functions


def index(video_path: str | Path, persist_dir: str | Path | None = None):
    """Transcrit + indexe une vidéo (Chroma). Retourne le vectorstore."""
    fn = _import_functions()
    transcript_path, segments = fn.transcribe_video(str(video_path))
    pdir = str(persist_dir) if persist_dir else str(_CACHE / "chroma" / Path(video_path).stem)
    return fn.index_video(transcript_path, persist_dir=pdir, segments=segments)


def query(video_path: str | Path, question: str) -> dict:
    """
    Interroge une vidéo indexée. Retourne {"answer": str, "frames": [paths]}.
    Réponse Gemini (GOOGLE_API_KEY) + frames extraites aux moments pertinents.
    """
    fn = _import_functions()
    return fn.get_rag_response(str(video_path), question)


def index_folder(folder: str | Path, pattern: str = "*.MP4") -> dict:
    """Indexe toutes les vidéos d'un dossier (ex: 'Video pub preuve/'). Résumé."""
    folder = Path(folder)
    vids = list(folder.glob(pattern)) + list(folder.glob(pattern.lower()))
    done, errors = 0, 0
    for v in vids:
        try:
            index(v)
            done += 1
        except Exception:
            errors += 1
    return {"folder": str(folder), "indexed": done, "errors": errors, "total": len(vids)}


if __name__ == "__main__":
    # self-check sans deps lourdes : vérifie juste la structure du wrapper.
    assert REPO.endswith("Video-RAG")
    print(f"video_rag: wrapper OK — repo={REPO}")
    print(f"  cache prévu : {_CACHE}")
    print("  ensure() cl-one+installe au 1er appel (whisper/torch/chroma/ffmpeg)")
    print("  API: ensure() | index(path) | query(path,q) | index_folder(dir)")
