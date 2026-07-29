"""test_strategy_behaviour.py — tests de COMPORTEMENT des détecteurs SMC.

POURQUOI
--------
`test_surface.py` prouve qu'aucun symbole ne disparaît lors d'un déplacement de fichiers.
Il ne prouve RIEN sur les calculs : une fonction pourrait retourner des résultats
différents et passer. Or la consolidation (W5-03g) réécrit des imports dans 48 modules —
il faut pouvoir affirmer que la détection donne toujours les mêmes signaux.

Ces tests épinglent le comportement observable sur des données SYNTHÉTIQUES et
DÉTERMINISTES : un FVG construit à la main doit être détecté, une série plate ne doit
rien produire, les bornes doivent être cohérentes.

Ce sont des tests de *caractérisation* : ils figent ce que le code fait aujourd'hui, sans
juger si c'est la bonne stratégie de trading. Leur rôle est de détecter un CHANGEMENT,
pas de valider la finance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FORGE_ROOT = Path(__file__).resolve().parents[2]
for p in (FORGE_ROOT, FORGE_ROOT / "00_CORE"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pd = pytest.importorskip("pandas", reason="pandas requis pour les stratégies")


def _ohlc(rows: list) -> "pd.DataFrame":
    """Construit un DataFrame OHLC depuis [(open, high, low, close), …]."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _flat(n: int = 30, price: float = 100.0) -> "pd.DataFrame":
    """Série strictement plate : aucun signal ne doit en sortir."""
    return _ohlc([(price, price, price, price)] * n)


# ── FVG : le cas d'école, construit à la main ────────────────────────────────

def test_fvg_bullish_detecte_sur_gap_construit():
    """high[i-1] < low[i+1] ⇒ FVG haussier. Gap posé explicitement entre les barres 0 et 2."""
    from forge_trading.strategies.smc_strategy import detect_fvg

    data = _ohlc([
        (100, 101, 99, 100),     # 0 : high = 101
        (102, 106, 101, 105),    # 1 : la bougie qui déplace
        (105, 108, 104, 107),    # 2 : low = 104 > high[0] = 101  → gap
        (107, 108, 106, 107),
    ])
    fvgs = detect_fvg(data, min_gap_pct=0.0001)
    assert fvgs, "un gap haussier explicite doit être détecté"
    kinds = {getattr(f, "type", getattr(f, "direction", "")) for f in fvgs}
    assert any("bull" in str(k).lower() for k in kinds), f"type attendu bullish, obtenu {kinds}"


def test_fvg_aucun_sur_serie_plate():
    """Une série sans mouvement ne doit produire aucun signal — anti-faux-positif."""
    from forge_trading.strategies.smc_strategy import detect_fvg

    assert detect_fvg(_flat(), min_gap_pct=0.0001) == []


def test_fvg_seuil_filtre_les_micro_gaps():
    """Un seuil élevé doit éliminer un gap minuscule : le paramètre agit vraiment."""
    from forge_trading.strategies.smc_strategy import detect_fvg

    data = _ohlc([
        (100, 100.10, 99.9, 100.0),
        (100, 100.30, 100.0, 100.2),
        (100, 100.40, 100.11, 100.3),   # gap ~0.01 %
        (100, 100.40, 100.20, 100.3),
    ])
    petit = detect_fvg(data, min_gap_pct=0.00001)
    grand = detect_fvg(data, min_gap_pct=0.50)
    assert len(grand) <= len(petit), "un seuil plus strict ne peut pas produire PLUS de signaux"
    assert grand == [] or len(grand) < len(petit)


# ── Order blocks & structure ─────────────────────────────────────────────────

def test_order_blocks_serie_plate_est_vide():
    from forge_trading.strategies.smc_strategy import detect_order_blocks

    assert detect_order_blocks(_flat(40), lookback=5) == []


def test_structure_breaks_serie_plate_est_vide():
    from forge_trading.strategies.smc_strategy import detect_structure_breaks

    assert detect_structure_breaks(_flat(40), swing_lookback=5) == []


def test_structure_breaks_exige_deux_sommets_croissants():
    """BOS haussier = deux swing highs consécutifs, le second plus haut.

    Comportement caractérisé, contre-intuitif au premier abord : une progression
    strictement monotone ne produit AUCUNE cassure, car chaque barre dépasse la
    précédente et aucun sommet local ne se forme. Il faut sommet → repli → sommet
    plus haut, avec assez de barres de part et d'autre (la fenêtre `swing_lookback`
    exclut les `lookback` premières et dernières barres).
    """
    from forge_trading.strategies.smc_strategy import detect_structure_breaks

    rows = [(100, 101, 99, 100)] * 5
    rows += [(100, 110, 99, 109)]              # sommet 1
    rows += [(100, 101, 99, 100)] * 5          # repli
    rows += [(100, 120, 99, 119)]              # sommet 2, plus haut → BOS
    rows += [(100, 101, 99, 100)] * 5          # marge pour confirmer le sommet 2
    breaks = detect_structure_breaks(_ohlc(rows), swing_lookback=3)

    assert len(breaks) == 1, f"un seul BOS attendu, obtenu {breaks}"
    bos = breaks[0]
    assert bos.direction == "bullish_bos"
    assert float(bos.level) == 120.0


def test_structure_breaks_ignore_progression_monotone():
    """Le pendant du test précédent : sans sommet local, aucune cassure."""
    from forge_trading.strategies.smc_strategy import detect_structure_breaks

    rows = [(100 + i * 2, 102 + i * 2, 99 + i * 2, 101 + i * 2) for i in range(24)]
    assert detect_structure_breaks(_ohlc(rows), swing_lookback=3) == []


# ── smc_v3 : swing points ────────────────────────────────────────────────────

def test_swing_points_trouve_le_sommet():
    """Un pic unique et net doit ressortir comme swing high."""
    from forge_trading.strategies.smc_v3 import find_swing_points

    rows = [(100, 101, 99, 100)] * 5
    rows += [(100, 120, 99, 118)]              # pic isolé
    rows += [(100, 101, 99, 100)] * 5
    highs, lows = find_swing_points(_ohlc(rows), lookback=2)
    assert highs, "le pic doit produire un swing high"
    assert max(h[1] for h in highs) == 120


def test_swing_points_serie_plate_ne_leve_pas():
    """Cas dégénéré : aucune variation. Doit renvoyer des listes, pas planter."""
    from forge_trading.strategies.smc_v3 import find_swing_points

    highs, lows = find_swing_points(_flat(20), lookback=2)
    assert isinstance(highs, list) and isinstance(lows, list)


# ── smc_engine (00_CORE) ─────────────────────────────────────────────────────

def test_smc_engine_swing_points_renvoie_deux_series():
    from forge_trading.core.smc_engine import swing_points

    hi, lo = swing_points(_flat(30), k=3)
    assert len(hi) == 30 and len(lo) == 30, "une valeur par barre"


def test_smc_engine_detect_setup_sans_signal_sur_serie_plate():
    """Aucun setup sur une série plate — et surtout : aucune exception."""
    from forge_trading.core.smc_engine import detect_setup

    out = detect_setup(_flat(60), bias=None)
    assert out is None or hasattr(out, "__dict__")


# ── Déterminisme : la garantie qui rend le déplacement vérifiable ────────────

def test_detecteurs_sont_deterministes():
    """Deux appels sur les mêmes données donnent le même résultat.

    Sans déterminisme, aucune comparaison avant/après déplacement n'aurait de sens.
    """
    from forge_trading.strategies.smc_strategy import detect_fvg, detect_order_blocks

    rows = [(100 + (i % 7), 102 + (i % 5), 98 + (i % 3), 100 + (i % 4)) for i in range(60)]
    data = _ohlc(rows)
    assert [str(x) for x in detect_fvg(data)] == [str(x) for x in detect_fvg(data)]
    assert [str(x) for x in detect_order_blocks(data)] == [str(x) for x in detect_order_blocks(data)]
