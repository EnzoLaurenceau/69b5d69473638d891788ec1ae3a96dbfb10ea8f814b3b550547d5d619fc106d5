"""Le cloisonnement d'état est-il réel, vu depuis un module migré ?

`forge_store` a ses propres tests, mais ils testent `forge_store`. Ce qu'on veut savoir
ici est différent et c'est la seule chose qui compte pour expédier : **un module ordinaire
de la Forge, migré par l'outil, écrit-il vraiment dans l'espace de son tenant ?**

Le module cobaye est `forge_dispatch.kanban` : c'est le board de tâches — s'il fuit,
un client voit les tâches d'un autre. Cas le plus concret possible.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.forge_store import TENANTS_ROOT, state_path  # noqa: E402
from forge_agents.forge_tenant import TenantError, tenant_scope  # noqa: E402
from forge_dispatch import kanban  # noqa: E402

A, B = "iso-alpha", "iso-beta"


@pytest.fixture(autouse=True)
def _clean():
    for t in (A, B):
        shutil.rmtree(TENANTS_ROOT / t, ignore_errors=True)
    yield
    for t in (A, B):
        shutil.rmtree(TENANTS_ROOT / t, ignore_errors=True)


def test_deux_tenants_ne_partagent_pas_le_board():
    with tenant_scope(A):
        kanban.save({"tasks": [{"id": "secret-de-A"}], "version": 1})
    with tenant_scope(B):
        board = kanban.load()
        assert board["tasks"] == [], "B voit les tâches de A — le cloisonnement ne tient pas"
        kanban.save({"tasks": [{"id": "propre-a-B"}], "version": 1})
    with tenant_scope(A):
        assert [t["id"] for t in kanban.load()["tasks"]] == ["secret-de-A"], \
            "B a écrasé le board de A"


def test_le_fichier_est_physiquement_dans_l_espace_du_tenant():
    with tenant_scope(A):
        kanban.save({"tasks": [], "version": 1})
        p = kanban.KANBAN_FILE()
    assert str(p).startswith(str(TENANTS_ROOT / A)), f"écrit hors de l'espace du tenant: {p}"
    assert p.exists()


def test_mode_transition_sans_tenant_reste_sur_le_chemin_historique(monkeypatch):
    """Migrer module par module ne doit pas casser l'usage mono-utilisateur existant."""
    monkeypatch.delenv("FORGE_SINGLE_TENANT", raising=False)
    monkeypatch.delenv("FORGE_TENANT_STRICT", raising=False)
    assert kanban.KANBAN_FILE() == ROOT / "05_STATE" / "kanban" / "board.json"


def test_mode_strict_refuse_d_ecrire_sans_tenant(monkeypatch):
    """La CI tourne en strict : un module qui oublie le scope doit échouer bruyamment."""
    monkeypatch.delenv("FORGE_SINGLE_TENANT", raising=False)
    monkeypatch.setenv("FORGE_TENANT_STRICT", "1")
    with pytest.raises(TenantError):
        kanban.KANBAN_FILE()


def test_aucun_module_migre_n_est_casse_en_mode_script():
    """Un import relatif nu casse un module lancé en script — la CI en lance.

    C'est une régression réellement introduite par la migration W5-03a : `python
    00_CORE/forge_agents/tech_debt.py` (porte 4 de la CI) échouait sur
    « attempted relative import with no known parent package ». Vérification statique,
    donc sans effet de bord : un module qui a un bloc `__main__` ne doit pas avoir
    d'import relatif de `state_path` au niveau du module, hors bloc gardé.
    """
    casses = []
    for p in (ROOT / "00_CORE").rglob("*.py"):
        if "__pycache__" in str(p) or "rtk" in p.parts:
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        if "state_path" not in t or '__name__ == "__main__"' not in t:
            continue
        if "from .forge_store import state_path" in t and "except ImportError" not in t:
            casses.append(p.relative_to(ROOT).as_posix())
    assert not casses, f"import relatif nu dans un module lançable en script : {casses}"


def test_une_cle_d_un_tenant_ne_peut_pas_designer_celle_d_un_autre():
    with tenant_scope(A):
        with pytest.raises(Exception):
            state_path(f"../{B}/kanban/board.json")
