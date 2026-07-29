"""
kb_manager.py — Knowledge Base L3 (Cold Memory)
================================================
Gère la couche de mémoire froide : skills validés par MiroFish,
patterns de succès, anti-patterns, et prompts optimisés.

Architecture mémoire complète :
  L1 Hot   → ForgeState + SQLite (session)          [déjà existant]
  L2 Warm  → OpenViking + Graphify (cross-session)   [déjà existant]
  L3 Cold  → Knowledge Base (ce module)              [NOUVEAU]

La KB ne reçoit QUE des findings approuvés par MiroFish Gate 1 (kb_intake).
Threshold : consensus ≥ 0.70

Usage :
  from forge_agents.kb_manager import get_kb_manager
  kb = get_kb_manager()

  # Lookup avant création d'un agent
  skill = kb.lookup("analyse de marché IA", threshold=0.75)
  if skill:
      use_existing_skill(skill)

  # Ajouter un skill depuis un finding approuvé
  kb.add_skill_from_finding(finding, mirofish_verdict)

  # Stats
  print(kb.stats())
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger("KBManager")

FORGE_ROOT = Path(__file__).parent.parent.parent
KB_ROOT    = FORGE_ROOT / "07_KNOWLEDGE_BASE"

# Sous-dossiers
KB_SKILLS       = KB_ROOT / "skills"
KB_PATTERNS     = KB_ROOT / "patterns"
KB_ANTI         = KB_ROOT / "anti_patterns"
KB_TOKEN_OPT    = KB_ROOT / "token_optimizations"
KB_SCHEMA       = KB_ROOT / "schema.json"
KB_INDEX        = KB_ROOT / "index.json"  # index rapide pour lookup


# ─── Init KB structure ────────────────────────────────────────────────────────

def _init_kb() -> None:
    """Crée la structure KB si elle n'existe pas."""
    for folder in [KB_SKILLS, KB_PATTERNS, KB_ANTI, KB_TOKEN_OPT]:
        folder.mkdir(parents=True, exist_ok=True)

    if not KB_SCHEMA.exists():
        schema = {
            "version": "1.0",
            "skill": {
                "id": "KB-SKILL-xxx",
                "name": "string",
                "prompt": "string",
                "trigger_keywords": ["list of strings"],
                "performance": {
                    "avg_score": "float 0-10",
                    "uses": "int",
                    "last_used": "YYYY-MM-DD"
                },
                "mirofish_approval": {
                    "consensus": "float 0-1",
                    "approved_at": "YYYY-MM-DD",
                    "fallback_used": "bool"
                },
                "source_finding_id": "F-AGENT-xxx",
                "tier": "FREE|HAIKU|SONNET",
                "task_type": "string",
                "status": "active|archived|draft"
            }
        }
        KB_SCHEMA.write_text(json.dumps(schema, indent=2, ensure_ascii=False))

    if not KB_INDEX.exists():
        KB_INDEX.write_text(json.dumps({"skills": [], "patterns": [], "anti_patterns": []},
                                        indent=2, ensure_ascii=False))


# ─── KBManager ────────────────────────────────────────────────────────────────

class KBManager:
    """
    CRUD + lookup sémantique pour la Knowledge Base L3.
    """

    def __init__(self):
        _init_kb()
        self._index: dict = self._load_index()

    # ── LOOKUP ────────────────────────────────────────────────────────────────

    def lookup(self, query: str, threshold: float = 0.75) -> Optional[dict]:
        """
        Cherche un skill correspondant à la query.
        Utilise un scoring keyword simple (pas de vecteurs — gratuit).
        Retourne le skill dict ou None si aucun match ≥ threshold.
        """
        query_tokens = set(self._tokenize(query))
        best_score  = 0.0
        best_skill  = None

        for entry in self._index.get("skills", []):
            if entry.get("status") != "active":
                continue

            # Score basé sur les trigger_keywords
            keywords = set(entry.get("trigger_keywords", []))
            if not keywords:
                continue

            # Jaccard similarity entre query et keywords
            intersection = query_tokens & keywords
            union        = query_tokens | keywords
            score        = len(intersection) / len(union) if union else 0.0

            # Bonus performance (avg_score normalisé)
            avg = entry.get("avg_score", 5.0) / 10.0
            score = score * 0.7 + avg * 0.3

            if score > best_score:
                best_score = score
                best_skill = entry

        if best_score >= threshold and best_skill:
            logger.info(f"[KB-LOOKUP] Match: '{best_skill['name']}' (score={best_score:.2f})")
            # Charger le skill complet depuis le fichier
            skill_path = KB_SKILLS / f"{best_skill['id']}.json"
            if skill_path.exists():
                skill = json.loads(skill_path.read_text(encoding="utf-8"))
                # Incrémenter uses
                self._increment_uses(best_skill["id"])
                return skill

        return None

    # ── ADD SKILL ─────────────────────────────────────────────────────────────

    def add_skill_from_finding(self, finding: dict, verdict) -> str:
        """
        Crée un skill KB depuis un finding approuvé par MiroFish.
        verdict : MiroVerdict (de mirofish.py)
        Retourne l'ID du skill créé.

        Génère un prompt réutilisable structuré (pas le finding brut).
        """
        skill_id = f"KB-SKILL-{uuid.uuid4().hex[:6].upper()}"

        # Extraire les keywords du contenu (heuristique simple)
        content  = finding.get("content", "")
        title    = finding.get("title", "")
        agent    = finding.get("agent", "general")
        score    = finding.get("score", 5.0)
        keywords = self._extract_keywords(content)

        # Inférer le tier recommandé depuis le score
        tier  = "FREE" if score < 7.0 else ("HAIKU" if score < 9.0 else "SONNET")

        # Générer un prompt réutilisable structuré (pas le finding brut)
        reusable_prompt = self._generate_reusable_prompt(title, content, agent, score)

        skill = {
            "id": skill_id,
            "name": self._generate_skill_name(content) or title,
            "prompt": reusable_prompt,
            "trigger_keywords": keywords,
            "performance": {
                "avg_score": score,
                "uses": 0,
                "last_used": str(date.today()),
            },
            "mirofish_approval": {
                "consensus": verdict.consensus,
                "approved_at": str(date.today()),
                "fallback_used": verdict.fallback_used,
            },
            "source_finding_id": finding.get("id", "?"),
            "source_agent": agent,
            "tier": tier,
            "task_type": agent.lower(),
            "status": "active",
            "created_at": str(date.today()),
        }

        # Écrire le fichier skill
        skill_path = KB_SKILLS / f"{skill_id}.json"
        skill_path.write_text(json.dumps(skill, indent=2, ensure_ascii=False))

        # Mettre à jour l'index
        self._index["skills"].append({
            "id": skill_id,
            "name": skill["name"],
            "trigger_keywords": keywords,
            "avg_score": skill["performance"]["avg_score"],
            "uses": 0,
            "status": "active",
            "created_at": str(date.today()),
        })
        self._save_index()

        logger.info(f"[KB] Skill créé : {skill_id} '{skill['name']}' (consensus={verdict.consensus:.2f})")
        return skill_id

    def _generate_reusable_prompt(self, title: str, content: str, agent: str, score: float) -> str:
        """
        Traduit un finding factuel en instruction réutilisable structurée.
        Au lieu de copier le finding brut, génère un prompt-actionnable.
        """
        # Extraire les faits clés du contenu
        facts = []
        for line in content.split("\n"):
            line = line.strip()
            if line and len(line) > 10 and not line.startswith("#"):
                # Garder les lignes informatives
                if any(kw in line.lower() for kw in ("use", "utilise", "applique", "évite", "avoid", "important", "note", "astuce", "tip", "pattern", "méthode", "method")):
                    facts.append(f"- {line}")
                elif len(facts) < 5 and len(line) < 200:
                    facts.append(f"- {line}")

        # Si pas assez de faits, extraire les phrases principales
        if len(facts) < 2:
            sentences = [s.strip() for s in content.replace(".", ".\n").split("\n") if s.strip() and len(s.strip()) > 15]
            facts = [f"- {s}" for s in sentences[:5]]

        facts_str = "\n".join(facts[:8]) if facts else f"- {content[:200]}"

        # Générer le prompt structuré
        domain = agent.replace("_", " ").title()
        return f"""# Compétence Apprise : {title or 'Sans titre'}

## Rôle
Tu es un assistant spécialisé dans {domain}.

## Instruction Réutilisable
Pour accomplir cette tâche avec succès, applique la méthodologie validée :
{facts_str}

## Critères de Succès
- Valider le score supérieur à {score:.1f}/10
- Appliquer les patterns éprouvés ci-dessus
- Documenter les écarts par rapport à la méthodologie

## Source
- Agent: {agent}
- Score original: {score:.1f}/10
"""

    # ── ADD TOKEN OPTIMIZATION ────────────────────────────────────────────────

    def add_token_optimization(self, original_prompt: str, optimized_prompt: str,
                                verdict, task_type: str = "general") -> str:
        """Stocke une variante de prompt optimisée validée par MiroFish Gate 3."""
        opt_id = f"KB-TOKEN-{uuid.uuid4().hex[:6].upper()}"
        orig_tokens = len(original_prompt.split()) * 1.3
        opt_tokens  = len(optimized_prompt.split()) * 1.3
        ratio = opt_tokens / orig_tokens if orig_tokens > 0 else 1.0

        entry = {
            "id": opt_id,
            "task_type": task_type,
            "original_tokens": int(orig_tokens),
            "optimized_tokens": int(opt_tokens),
            "compression_ratio": round(ratio, 2),
            "optimized_prompt": optimized_prompt,
            "mirofish_consensus": verdict.consensus,
            "created_at": str(date.today()),
        }

        opt_path = KB_TOKEN_OPT / f"{opt_id}.json"
        opt_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False))

        if "token_optimizations" not in self._index:
            self._index["token_optimizations"] = []
        self._index["token_optimizations"].append({
            "id": opt_id, "task_type": task_type,
            "ratio": ratio, "created_at": str(date.today())
        })
        self._save_index()

        logger.info(f"[KB] Token opt créé : {opt_id} (ratio={ratio:.0%}, consensus={verdict.consensus:.2f})")
        return opt_id

    # ── ADD PATTERN / ANTI-PATTERN ────────────────────────────────────────────

    def add_pattern(self, content: str, pattern_type: str = "pattern",
                    source: str = "mirofish") -> str:
        """Stocke un pattern de succès ou anti-pattern."""
        pat_id   = f"KB-PAT-{uuid.uuid4().hex[:6].upper()}"
        folder   = KB_ANTI if pattern_type == "anti_pattern" else KB_PATTERNS
        entry    = {
            "id": pat_id, "type": pattern_type, "content": content,
            "source": source, "created_at": str(date.today()),
        }
        (folder / f"{pat_id}.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False)
        )
        key = "anti_patterns" if pattern_type == "anti_pattern" else "patterns"
        self._index.setdefault(key, []).append(
            {"id": pat_id, "preview": content[:80], "created_at": str(date.today())}
        )
        self._save_index()
        return pat_id

    # ── BULK DATASET INGEST (Fine-Tuning) ────────────────────────────────────

    def bulk_ingest_dataset(self, dataset_id: str, source_path: Path,
                            purpose: str = "fine-tuning") -> dict:
        """
        Ingère un dataset entier dans la KB sans créer N fichiers individuels.
        Stocke une référence indexée + métadonnées dans l'index.
        Pour le fine-tuning : le dataset reste en JSONL compact.
        """
        if not source_path.exists():
            logger.error(f"[KB] Dataset source not found: {source_path}")
            return {"error": "source_not_found"}

        # Count rows
        row_count = sum(1 for _ in open(source_path, "r", encoding="utf-8"))

        # Register in index
        datasets = self._index.setdefault("datasets", [])
        # Remove old entry if exists
        datasets[:] = [d for d in datasets if d.get("id") != dataset_id]

        entry = {
            "id": dataset_id,
            "path": str(source_path),
            "rows": row_count,
            "purpose": purpose,
            "size_bytes": source_path.stat().st_size,
            "ingested_at": str(date.today()),
            "status": "active",
        }
        datasets.append(entry)
        self._save_index()

        logger.info(f"[KB] Dataset ingested: {dataset_id} ({row_count} rows, {purpose})")
        return entry

    def get_finetune_datasets(self) -> list[dict]:
        """Liste tous les datasets de fine-tuning disponibles."""
        return [
            d for d in self._index.get("datasets", [])
            if d.get("purpose") == "fine-tuning" and d.get("status") == "active"
        ]

    def trigger_finetune_pipeline(self, output_format: str = "chatml",
                                   max_samples: int = None) -> str:
        """Déclenche le pipeline de fine-tuning complet."""
        try:
            from .finetune_pipeline import get_finetune_pipeline
            pipe = get_finetune_pipeline()
            pipe.generate_forge_experience()
            output_path = pipe.prepare(
                output_format=output_format,
                max_samples=max_samples,
            )
            return str(output_path)
        except Exception as e:
            logger.error(f"[KB] Finetune pipeline error: {e}")
            return f"error: {e}"

    # ── STATS ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Retourne les statistiques de la KB."""
        skills = self._index.get("skills", [])
        active = [s for s in skills if s.get("status") == "active"]
        datasets = self._index.get("datasets", [])
        ft_datasets = [d for d in datasets if d.get("purpose") == "fine-tuning"]
        return {
            "total_skills": len(skills),
            "active_skills": len(active),
            "patterns": len(self._index.get("patterns", [])),
            "anti_patterns": len(self._index.get("anti_patterns", [])),
            "token_optimizations": len(self._index.get("token_optimizations", [])),
            "datasets": len(datasets),
            "finetune_datasets": len(ft_datasets),
            "finetune_total_rows": sum(d.get("rows", 0) for d in ft_datasets),
            "top_skills": sorted(active, key=lambda x: x.get("uses", 0), reverse=True)[:5],
        }

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _load_index(self) -> dict:
        if KB_INDEX.exists():
            try:
                return json.loads(KB_INDEX.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return {"skills": [], "patterns": [], "anti_patterns": [], "token_optimizations": []}

    def _save_index(self) -> None:
        KB_INDEX.write_text(json.dumps(self._index, indent=2, ensure_ascii=False))

    def _increment_uses(self, skill_id: str) -> None:
        """Incrémente uses dans l'index et le fichier skill."""
        for entry in self._index.get("skills", []):
            if entry["id"] == skill_id:
                entry["uses"] = entry.get("uses", 0) + 1
                break
        self._save_index()
        skill_path = KB_SKILLS / f"{skill_id}.json"
        if skill_path.exists():
            try:
                skill = json.loads(skill_path.read_text(encoding="utf-8"))
                skill["performance"]["uses"] += 1
                skill["performance"]["last_used"] = str(date.today())
                skill_path.write_text(json.dumps(skill, indent=2, ensure_ascii=False))
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenise un texte en mots-clés significatifs (min 3 chars)."""
        words = re.findall(r'\b[a-zA-ZÀ-ÿ]{3,}\b', text.lower())
        # Stopwords FR/EN basiques
        stops = {"les", "des", "pour", "dans", "que", "qui", "une", "est", "the",
                 "and", "for", "with", "this", "that", "are", "has", "have"}
        return [w for w in words if w not in stops]

    @staticmethod
    def _extract_keywords(content: str) -> list[str]:
        """Extrait les 10 mots-clés les plus représentatifs du contenu."""
        from collections import Counter
        words = KBManager._tokenize(content)
        freq  = Counter(words)
        return [w for w, _ in freq.most_common(10)]

    @staticmethod
    def _generate_skill_name(content: str) -> str:
        """Génère un nom de skill à partir du contenu (heuristique)."""
        words = KBManager._tokenize(content)
        if len(words) >= 2:
            return "_".join(w.capitalize() for w in words[:3])
        return f"Skill_{uuid.uuid4().hex[:4].upper()}"


# ─── Singleton ────────────────────────────────────────────────────────────────

_kb_instance: Optional[KBManager] = None

def get_kb_manager() -> KBManager:
    """Retourne le singleton KBManager (lazy init)."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KBManager()
    return _kb_instance
