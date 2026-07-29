"""
world_canon.py — canon source, index de citations, gate copyright (ticket E2-03)
================================================================================
Le monde s'inspire d'une œuvre existante (*Le Livre du Nouveau Soleil*). Deux
besoins en découlent, et un seul module les sert parce qu'ils sont le même
problème vu des deux côtés :

- **attribuer** — « d'où vient cette phrase ? » doit avoir une réponse, sinon
  « inspiration » n'est qu'un mot qu'on s'accorde à soi-même ;
- **empêcher la copie** — un jeu commercial qui recopie son inspiration est un
  risque juridique réel (audit §22 : « pas de gate licence/copyright — risque
  juridique réel »).

LA DÉCISION QUI COMMANDE TOUT : ON N'INDEXE PAS LE TEXTE
--------------------------------------------------------
L'index ne contient **aucun mot de l'œuvre**. Il ne garde que des empreintes
(sha1 de fenêtres glissantes de mots normalisés) et des repères de position.
On ne peut pas reconstruire la source depuis l'index — c'est vérifié par un test.

Ce n'est pas un raffinement, c'est le cœur du ticket : **un gate copyright qui
conserve une copie de l'œuvre pour se défendre EST la fuite qu'il prétend
empêcher.** Le fichier source reste dehors, fourni par un humain qui en a les
droits, lu une fois, jamais recopié dans le dépôt.

POURQUOI PAS `dataset_rag` (malgré l'intitulé du ticket)
---------------------------------------------------------
L'audit dit « → `dataset_rag.py` ». `dataset_rag` est un corpus de RECHERCHE :
il rend des extraits pour les injecter dans un prompt. Y verser le canon
reviendrait à mettre le texte de l'œuvre dans le contexte d'un modèle qui doit
produire du contenu original — c'est le chemin le plus court vers la copie
verbatim, pas le plus court vers l'inspiration. Même logique qu'E2-02, qui a
refusé de bâtir l'unicité sur `forge_fingerprint` malgré l'intitulé : l'outil
nommé ne répondait pas à la question posée.

Ce module donne donc l'ATTRIBUTION (où ça se trouve dans l'œuvre) et le REFUS
(ceci est recopié). Ce qu'un agent lit pour s'inspirer, c'est le World-KG
(E2-01) — des entités, pas de la prose.

LES SEUILS NE SONT PAS INVENTÉS
--------------------------------
`CLAUDE.md` §3 les fixe déjà pour toute la Forge : « Limite STRICTE de 1
citation/source max (15 mots max). C'est une VIOLATION SÉVÈRE de dépasser
cela. » `MAX_QUOTE_WORDS` et `MAX_QUOTES` ne font que rendre cette règle
exécutable. Les changer ici serait changer la doctrine en douce.

COMMENT ON S'EN SERT
--------------------
    from forge_agents.world_canon import get_canon, CopyrightViolation

    c = get_canon()
    c.ingest_file("D:/hors-depot/nouveau-soleil.txt",   # RESTE hors du dépôt
                  work="Le Livre du Nouveau Soleil",
                  license="tous droits réservés")

    c.attribute(texte)   # → d'où ça vient (repères, jamais de texte)
    c.check(texte)       # → verdict chiffré
    c.guard(texte)       # → lève CopyrightViolation si ça recopie

Vérification : `python -m forge_agents.world_canon` · `pytest test_world_canon.py`
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

from .world_kg import slugify
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

#: Longueur de la fenêtre glissante, en mots. Deux contraintes opposées : trop
#: courte, des tournures banales (« il ne savait pas ce qui ») collisionnent et
#: le gate crie au loup ; trop longue, une copie plus courte que la fenêtre
#: devient indétectable. 8 tient sous la limite doctrinale de 15 mots — une
#: fenêtre plus longue rendrait le seuil de CLAUDE.md invérifiable.
SHINGLE_WORDS = 8

#: Doctrine `CLAUDE.md` §3, rendue exécutable. NE PAS assouplir ici : ce fichier
#: n'est pas le bon endroit pour changer une règle qui vaut pour toute la Forge.
MAX_QUOTE_WORDS = 15
MAX_QUOTES = 1

#: Taille d'un repère de citation, en mots. Le repère dit OÙ (« passage 42 »),
#: jamais QUOI — c'est ce qui permet de citer proprement sans rien conserver.
CHUNK_WORDS = 200

_WORD_RE = re.compile(r"\w+", re.UNICODE)


class CopyrightViolation(RuntimeError):
    """Le texte recopie une source indexée au-delà de ce que la doctrine permet.

    Porte `report` (le verdict complet de `check()`) pour qu'un appelant
    automatique puisse décider — reformuler, raccourcir, ou escalader en HITL.
    """

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def normalize(text: str) -> list[str]:
    """Texte → suite de mots normalisés (accents et casse neutralisés).

    Même normalisation que les clés d'E2-01 (`slugify` en amont), pour qu'une
    recopie maquillée par un changement de casse ou d'accents reste détectée.
    La ponctuation disparaît : elle est le premier déguisement d'un copier-coller.
    """
    norm = unicodedata.normalize("NFKD", str(text))
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return _WORD_RE.findall(norm.lower())


def shingles(words: Iterable[str], size: int = SHINGLE_WORDS) -> list[str]:
    """Fenêtres glissantes de `size` mots → empreintes sha1 tronquées.

    Tronquées à 16 hexa (64 bits) : sur un index d'un million de fenêtres, la
    probabilité d'une collision fortuite reste négligeable devant celle d'une
    tournure réellement partagée, et l'index tient trois fois moins de place.
    """
    seq = list(words)
    if len(seq) < size:
        return []
    return [hashlib.sha1(" ".join(seq[i:i + size]).encode("utf-8")).hexdigest()[:16]
            for i in range(len(seq) - size + 1)]


class CanonIndex:
    """Index d'empreintes des œuvres sources. Ne contient aucun texte.

    L'état est cloisonné par tenant (`state_path`) : le canon d'un client est le
    sien, et deux jeux qui s'inspirent d'œuvres différentes ne doivent pas se
    contaminer leurs verdicts.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else None
        self._data: Optional[dict] = None

    # ── Persistance ──────────────────────────────────────────────────────────

    def path(self) -> Path:
        if self._path is None:
            self._path = state_path("canon_index.json")
        return self._path

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        try:
            # utf-8-sig : sur cette plateforme tout JSON écrit depuis PowerShell
            # porte un BOM, et une lecture stricte lèverait sur le premier octet.
            raw = json.loads(self.path().read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raw = {}
        self._data = {"works": dict(raw.get("works") or {}),
                      "shingles": dict(raw.get("shingles") or {})}
        return self._data

    def _save(self) -> None:
        data = self._load()
        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # ── Ingestion ────────────────────────────────────────────────────────────

    def ingest_text(self, text: str, work: str, license: str = "",
                    chunk_words: int = CHUNK_WORDS) -> dict:
        """Indexe une œuvre à partir de son texte. **Le texte n'est pas conservé.**

        Renvoie le relevé de l'ingestion (mots lus, empreintes retenues). Ré-ingérer
        la même œuvre la REMPLACE plutôt que de l'accumuler : deux passes sur un
        fichier corrigé doubleraient sinon les empreintes sans rien apporter.
        """
        slug = slugify(work)
        if not slug:
            raise ValueError(f"nom d'œuvre inexploitable : {work!r}")
        words = normalize(text)
        if len(words) < SHINGLE_WORDS:
            raise ValueError(
                f"« {work} » : {len(words)} mot(s) — il en faut au moins "
                f"{SHINGLE_WORDS} pour une seule empreinte. Rien n'a été indexé.")

        data = self._load()
        self.forget(work, save=False)          # remplacement, jamais accumulation

        prints = shingles(words)
        for offset, fingerprint in enumerate(prints):
            locator = f"{slug}#{offset // max(1, chunk_words)}"
            data["shingles"].setdefault(fingerprint, [])
            if locator not in data["shingles"][fingerprint]:
                data["shingles"][fingerprint].append(locator)

        data["works"][slug] = {
            "title": work,
            "license": license,
            "words": len(words),
            "shingles": len(prints),
            "chunk_words": int(chunk_words),
        }
        self._save()
        return {"work": work, "slug": slug, "words": len(words),
                "shingles": len(prints), "license": license}

    def ingest_file(self, source: str | Path, work: str = "", license: str = "",
                    chunk_words: int = CHUNK_WORDS) -> dict:
        """Indexe une œuvre depuis un fichier — qui doit rester HORS du dépôt.

        Le fichier est lu une fois et jamais recopié. Le placer dans le dépôt
        annulerait tout l'intérêt du module : `refuse_repo_source()` le dit
        bruyamment plutôt que de l'accepter en silence.
        """
        path = Path(source)
        refuse_repo_source(path)
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        return self.ingest_text(text, work=work or path.stem,
                                license=license, chunk_words=chunk_words)

    def forget(self, work: str, save: bool = True) -> bool:
        """Retire une œuvre de l'index (droits retirés, source erronée…)."""
        data = self._load()
        slug = slugify(work)
        if slug not in data["works"]:
            return False
        prefix = f"{slug}#"
        for fingerprint in list(data["shingles"]):
            kept = [l for l in data["shingles"][fingerprint] if not l.startswith(prefix)]
            if kept:
                data["shingles"][fingerprint] = kept
            else:
                del data["shingles"][fingerprint]
        del data["works"][slug]
        if save:
            self._save()
        return True

    def works(self) -> list[dict]:
        """Les œuvres indexées, avec leur licence déclarée."""
        data = self._load()
        return [{"slug": s, **w} for s, w in sorted(data["works"].items())]

    # ── Attribution & gate ───────────────────────────────────────────────────

    def attribute(self, text: str) -> list[dict]:
        """D'où vient ce texte — l'index de citations du ticket.

        Renvoie les passages sources dont ce texte porte la trace, du plus
        recouvrant au moins. Des REPÈRES, jamais du texte : « passage 42 de
        telle œuvre » suffit à citer proprement, et n'expose rien.
        """
        data = self._load()
        hits: dict[str, int] = {}
        for fingerprint in shingles(normalize(text)):
            for locator in data["shingles"].get(fingerprint, ()):
                hits[locator] = hits.get(locator, 0) + 1
        out = []
        for locator, count in hits.items():
            slug, _, chunk = locator.partition("#")
            work = data["works"].get(slug, {})
            out.append({"work": work.get("title", slug), "slug": slug,
                        "passage": int(chunk or 0), "windows": count,
                        "license": work.get("license", "")})
        out.sort(key=lambda r: (-r["windows"], r["slug"], r["passage"]))
        return out

    def check(self, text: str) -> dict:
        """Verdict chiffré : ce texte recopie-t-il une source indexée ?

        Deux mesures, parce qu'elles attrapent deux fautes différentes :
        - la **plus longue reprise continue** attrape le copier-coller franc ;
        - le **nombre de reprises distinctes** attrape le patchwork — dix
          fragments de douze mots, chacun sous la limite, forment ensemble une
          copie que le seul critère de longueur laisserait passer.
        """
        data = self._load()
        words = normalize(text)
        prints = shingles(words)
        if not prints:
            return {"verdict": "ok", "blocked": False, "words": len(words),
                    "longest_run_words": 0, "quotes": 0, "overlap_pct": 0.0,
                    "matched_windows": 0, "sources": [], "reason": ""}

        flags = [fp in data["shingles"] for fp in prints]
        runs: list[int] = []
        current = 0
        for flag in flags:
            if flag:
                current += 1
            elif current:
                runs.append(current)
                current = 0
        if current:
            runs.append(current)

        # Une suite de k fenêtres consécutives couvre k + (taille - 1) mots.
        run_words = [r + SHINGLE_WORDS - 1 for r in runs]
        longest = max(run_words, default=0)
        # Une « citation » = une reprise continue qui atteint la longueur d'une
        # fenêtre. Compter chaque fenêtre isolée ferait un décompte de citations
        # sans rapport avec ce qu'un lecteur appellerait une citation.
        quotes = len(run_words)
        overlap = round(100 * sum(flags) / len(flags), 1)

        reasons = []
        if longest > MAX_QUOTE_WORDS:
            reasons.append(f"reprise continue de {longest} mots "
                           f"(maximum doctrinal {MAX_QUOTE_WORDS})")
        if quotes > MAX_QUOTES:
            reasons.append(f"{quotes} reprises distinctes "
                           f"(maximum doctrinal {MAX_QUOTES})")

        blocked = bool(reasons)
        return {
            "verdict": "blocked" if blocked else ("warn" if quotes else "ok"),
            "blocked": blocked,
            "words": len(words),
            "longest_run_words": longest,
            "quotes": quotes,
            "overlap_pct": overlap,
            "matched_windows": sum(flags),
            "sources": self.attribute(text),
            "reason": " · ".join(reasons),
        }

    def guard(self, text: str, what: str = "ce texte") -> dict:
        """`check()` qui LÈVE au lieu de rapporter. Renvoie le verdict si ça passe.

        C'est le point d'accroche d'**E3-07** (gate bloquant avant intégration).
        Ce ticket fournit le détecteur ; le poser dans le chemin de livraison
        des assets est l'autre ticket, et l'anticiper ici le rendrait infaisable
        proprement.
        """
        report = self.check(text)
        if report["blocked"]:
            citations = ", ".join(
                f"{s['work']} passage {s['passage']}" for s in report["sources"][:3])
            raise CopyrightViolation(
                f"{what} recopie une source indexée : {report['reason']}"
                + (f" — {citations}" if citations else "")
                + ". L'inspiration se reformule ; la copie ne se raccourcit pas.",
                report=report)
        return report


def refuse_repo_source(path: Path) -> None:
    """Refuse une source placée DANS le dépôt.

    Indexer un fichier du dépôt suppose que l'œuvre y a été copiée — ce que ce
    module existe précisément pour empêcher. On refuse le geste plutôt que de
    l'accepter en produisant un index parfaitement propre par-dessus une
    infraction déjà commise.
    """
    forge_root = Path(__file__).resolve().parents[2]
    try:
        inside = Path(path).resolve().is_relative_to(forge_root)
    except (OSError, ValueError):
        inside = False
    if inside:
        raise ValueError(
            f"source refusée : {path} est DANS le dépôt ({forge_root}). "
            f"Une œuvre sous droits ne se copie pas dans un dépôt de code — "
            f"gardez le fichier ailleurs, il n'est lu qu'une fois et jamais "
            f"recopié. Pour un texte de test, utilisez `ingest_text()`.")


_INDEX: dict[str, CanonIndex] = {}


def get_canon(path: Optional[Path] = None) -> CanonIndex:
    """Index du canon — un par chemin, cloisonné par tenant par défaut."""
    key = str(path) if path else "<tenant>"
    if key not in _INDEX:
        _INDEX[key] = CanonIndex(path)
    return _INDEX[key]


def reset_canon() -> None:
    """Détache les index (tests, changement de tenant)."""
    _INDEX.clear()


if __name__ == "__main__":  # self-check — n'écrit aucun état
    demo = ("Le soleil ancien se levait sur la ville aux murs de fer, "
            "et la lumiere tombait comme une poussiere lente sur les toits.")
    print(f"fenêtre {SHINGLE_WORDS} mots · citation max {MAX_QUOTE_WORDS} mots "
          f"· {MAX_QUOTES} citation(s) (doctrine CLAUDE.md §3)")
    mots = normalize(demo)
    print(f"démo : {len(mots)} mots → {len(shingles(mots))} empreintes")
    print("empreinte d'exemple :", shingles(mots)[0] if mots else "—")
    print("le texte est-il reconstructible depuis l'index ? non — "
          "l'index ne contient que des sha1 et des numéros de passage")
    idx = CanonIndex(Path("<mémoire>"))
    idx._data = {"works": {}, "shingles": {}}
    print("texte non indexé → verdict :", idx.check(demo)["verdict"])
