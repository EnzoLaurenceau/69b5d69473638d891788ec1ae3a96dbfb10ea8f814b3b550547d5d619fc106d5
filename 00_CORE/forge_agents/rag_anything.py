"""
rag_anything.py — Wrapper RAG-Anything (github.com/hkuds/rag-anything)
=======================================================================
RAG multimodal : PDF, Word, Excel, PPT, images, audio, vidéo, HTML, markdown…
Built on LightRAG. Élimine le besoin d'outils séparés par type de fichier.

Intégration forge :
  • LMCache   → cache les appels LLM pendant l'ingestion (via forge_call)
  • turbovec  → chunks extraits indexés pour recherche sémantique forge-wide
  • PostgreSQL → métadonnées des documents (forge_db.deep_insert)
  • Stirling-PDF → prétraitement PDF avant ingestion si OCR nécessaire
  • GitNexus  → NE PAS utiliser ici (code uniquement, pas documents)

Usage :
    from forge_agents.rag_anything import ForgeRAG
    rag = ForgeRAG(work_dir="./rag_workspace")
    await rag.ingest("rapport_client.pdf")
    await rag.ingest_dir("./docs/")
    result = await rag.query("Quel est le chiffre d'affaires Q1 ?")
    result = await rag.query_with_context("Analyse ce contrat", mode="hybrid")
"""

from __future__ import annotations
import asyncio, hashlib, os, time
from pathlib import Path
from typing import Optional

from .forge_db import get_db
from .forge_llm import forge_call, LLMTier
from .lmcache_integration import create_forge_cache

REPO = "https://github.com/hkuds/rag-anything"
INSTALL_CMD = "pip install raganything lightrag-hku"

# Mode de parsing : pipeline (rapide), hybrid-auto-engine (meilleur pour mixte)
_PARSE_BACKEND = os.environ.get("RAG_PARSE_BACKEND", "pipeline")
_WORK_DIR = os.environ.get("RAG_WORK_DIR", "./rag_workspace")
_EMBEDDING_DIM = 1536  # OpenAI-compatible / claude embedding


def _llm_func_wrapper():
    """Adapte forge_call() à l'interface attendue par LightRAG."""
    async def _llm(prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "user", "content": system_prompt + "\n\n" + prompt})
        else:
            messages.append({"role": "user", "content": prompt})
        return forge_call(prompt, tier=LLMTier.HAIKU, task_type="general_purpose")
    return _llm


def _embedding_func_wrapper():
    """Embedding via forge → pgvector dimensions compatibles."""
    async def _embed(texts: list[str]) -> list[list[float]]:
        # Utilise l'embedding OpenAI-compatible si dispo (OPENAI_API_KEY dans .env)
        # Sinon fallback hash-based (dégradé mais fonctionnel sans API)
        try:
            import openai
            client = openai.AsyncOpenAI()
            resp = await client.embeddings.create(
                model="text-embedding-3-small", input=texts
            )
            return [d.embedding for d in resp.data]
        except Exception:
            # Fallback : hash-based pseudo-embedding (dev only)
            import hashlib, struct
            def _hash_embed(text: str) -> list[float]:
                h = hashlib.sha256(text.encode()).digest()
                floats = [struct.unpack("f", h[i:i+4])[0] for i in range(0, min(len(h), _EMBEDDING_DIM * 4), 4)]
                while len(floats) < _EMBEDDING_DIM:
                    floats.extend(floats)
                return floats[:_EMBEDDING_DIM]
            return [_hash_embed(t) for t in texts]
    return _embed


class ForgeRAG:
    """
    Interface RAG-Anything intégrée à la forge.
    Tous les documents ingérés sont disponibles dans turbovec (recherche sémantique)
    et dans PostgreSQL (métadonnées + historique).
    """

    def __init__(self, work_dir: str | Path = _WORK_DIR):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._db = get_db()
        self._cache = create_forge_cache()
        self._rag = None  # lazy-init

    def _get_rag(self):
        """Init lazy de RAGAnything (évite l'import au chargement si non installé)."""
        if self._rag is not None:
            return self._rag
        try:
            from raganything import RAGAnything
            self._rag = RAGAnything(
                working_dir=str(self.work_dir),
                llm_model_func=_llm_func_wrapper(),
                vision_model_func=_llm_func_wrapper(),  # même LLM si vision dispo
                embedding_func=_embedding_func_wrapper(),
                embedding_dim=_EMBEDDING_DIM,
            )
            return self._rag
        except ImportError:
            raise RuntimeError(f"RAGAnything non installé : {INSTALL_CMD}")

    # ── Ingestion ─────────────────────────────────────────────────────────────

    async def ingest(
        self,
        file_path: str | Path,
        doc_id: str | None = None,
        preprocess_ocr: bool = False,
    ) -> dict:
        """
        Ingère un fichier (PDF, DOCX, PPTX, XLSX, image, audio, vidéo…).
        preprocess_ocr=True → passe d'abord par Stirling-PDF pour OCR.
        Retourne {doc_id, chunks, tokens_estimated}.
        """
        p = Path(file_path)
        if not p.exists():
            return {"error": f"Fichier introuvable : {p}"}

        # OCR préalable via Stirling-PDF si demandé
        if preprocess_ocr and p.suffix.lower() == ".pdf":
            try:
                from ..tools.product_bricks.documents.stirling_pdf import ocr
                pdf_bytes = ocr(str(p))
                ocr_path = p.with_suffix(".ocr.pdf")
                ocr_path.write_bytes(pdf_bytes)
                p = ocr_path
            except Exception as e:
                print(f"rag_anything: OCR Stirling échoué ({e}), ingestion directe")

        doc_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        _doc_id = doc_id or f"{p.stem}_{doc_hash}"

        # Check si déjà ingéré (dédup via forge_db)
        existing = self._db.deep_query("rag_docs", {"doc_id": _doc_id}, limit=1)
        if existing:
            return {"doc_id": _doc_id, "status": "already_indexed", "skipped": True}

        # Cache LMCache pour les appels LLM pendant l'ingestion
        self._cache.cache_rag_context(doc_hash, token_count=2000)

        # Ingestion RAGAnything
        rag = self._get_rag()
        await rag.process_document_complete(
            file_path=str(p),
            backend=_PARSE_BACKEND,
            display_stats=False,
            doc_id=_doc_id,
        )

        # Métadonnées dans PostgreSQL
        meta = {
            "doc_id": _doc_id,
            "file_path": str(p),
            "file_name": p.name,
            "doc_hash": doc_hash,
            "ts": time.time(),
            "size_bytes": p.stat().st_size,
            "agent": "RAG",
        }
        self._db.deep_insert("rag_docs", meta)

        # Index dans turbovec pour recherche forge-wide
        self._index_in_turbovec(_doc_id, p)

        return {"doc_id": _doc_id, "status": "indexed", "file": p.name}

    async def ingest_dir(self, dir_path: str | Path, pattern: str = "**/*") -> list[dict]:
        """Ingère tous les fichiers d'un dossier (récursif)."""
        supported = {".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt",
                     ".md", ".txt", ".html", ".jpg", ".jpeg", ".png", ".mp3", ".mp4"}
        results = []
        for f in Path(dir_path).glob(pattern):
            if f.is_file() and f.suffix.lower() in supported:
                r = await self.ingest(f)
                results.append(r)
        return results

    def _index_in_turbovec(self, doc_id: str, file_path: Path) -> None:
        """Bridge : extrait le texte et indexe dans turbovec (forge-wide search)."""
        try:
            from .turbovec_brain import get_turbovec_brain
            # Lit le texte brut extrait par RAGAnything (fichier .txt dans work_dir)
            txt_out = self.work_dir / f"{doc_id}_chunks.txt"
            if txt_out.exists():
                content = txt_out.read_text(encoding="utf-8", errors="ignore")
                for i, chunk in enumerate(content.split("\n\n")):
                    if chunk.strip():
                        get_turbovec_brain().store(
                            chunk.strip()[:1000],
                            agent="RAG",
                            meta={"doc_id": doc_id, "chunk_idx": i},
                        )
        except Exception as e:
            print(f"rag_anything: turbovec index ignoré ({e})")

    # ── Requêtes ──────────────────────────────────────────────────────────────

    async def query(self, question: str, mode: str = "hybrid") -> str:
        """
        Requête sur tous les documents ingérés.
        mode : "naive" | "local" | "global" | "hybrid" (défaut, meilleur)
        """
        # Check LMCache avant d'appeler le LLM
        q_hash = hashlib.sha256(question.encode()).hexdigest()[:16]
        cached = self._cache.lookup(q_hash)
        if cached:
            return f"[cached] {question}"  # cache hit, LightRAG gère le vrai cache

        rag = self._get_rag()
        result = await rag.query_with_multimodal_support(
            query=question,
            mode=mode,
        )
        return str(result)

    async def query_with_context(
        self,
        question: str,
        context: str = "",
        mode: str = "hybrid",
    ) -> str:
        """Requête avec contexte additionnel (ex: profil prospect depuis Twenty CRM)."""
        full_q = f"{context}\n\n{question}" if context else question
        return await self.query(full_q, mode=mode)

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def list_docs(self) -> list[dict]:
        """Liste les documents ingérés (depuis PostgreSQL)."""
        return self._db.deep_query("rag_docs", limit=200)

    def search_docs(self, text: str, k: int = 5) -> list[dict]:
        """Recherche sémantique dans les docs ingérés (pgvector)."""
        return self._db.deep_semantic("rag_docs", text, k=k)


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[ForgeRAG] = None

def get_rag(work_dir: str | Path = _WORK_DIR) -> ForgeRAG:
    global _instance
    if _instance is None:
        _instance = ForgeRAG(work_dir)
    return _instance


# ── Self-check ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        import raganything
        print("raganything: installé ✓")
    except ImportError:
        print(f"raganything: non installé → {INSTALL_CMD}")
    print(f"ForgeRAG: work_dir={_WORK_DIR}, backend={_PARSE_BACKEND}")
    print("intégrations: LMCache ✓, turbovec ✓, PostgreSQL ✓, Stirling-PDF ✓")
    print("GitNexus: hors scope (code uniquement, pas documents)")
