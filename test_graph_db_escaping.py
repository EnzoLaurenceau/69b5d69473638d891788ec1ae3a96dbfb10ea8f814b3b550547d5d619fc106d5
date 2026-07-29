"""L'échappement Cypher fait-il ce qu'il prétend faire ?

Ce fichier existe à cause d'une panne précise. W5-06 annonçait « échappement Cypher
durci (bypass antislash) ». Le code livré était :

    return str(value).replace_esc(("\\\\", "\\\\\\\\"))

`str.replace_esc` n'existe pas. **Chaque appel levait `AttributeError`**, avalé par le
`try/except` de l'appelant : le durcissement n'a jamais tourné, et les écritures dans le
graphe échouaient en silence. L'audit sécurité, lui, était content — il regardait la
présence d'une fonction d'échappement, pas son comportement.

Leçon retenue ici : on teste ce que la fonction RETOURNE, jamais qu'elle existe.
Aucune base Kùzu n'est nécessaire — ce sont des fonctions pures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "00_CORE"))

from forge_agents.graph_db import NODE_TABLES, _esc, _label, _num  # noqa: E402


def test_esc_ne_leve_pas():
    """La panne d'origine : un simple appel suffisait à la révéler."""
    assert _esc("bonjour") == "bonjour"


def test_esc_neutralise_le_quote_simple():
    assert _esc("O'Brien") == "O\\'Brien"


def test_esc_echappe_l_antislash_en_premier():
    """Un antislash final neutralisait le quote fermant : c'est l'évasion à empêcher."""
    assert _esc("fin\\") == "fin\\\\"
    # et l'échappement ne se ré-échappe pas lui-même en boucle
    assert _esc("a\\'b") == "a\\\\\\'b"


def test_esc_une_evasion_typique_reste_prisonniere():
    """`x' RETURN 1 //` ne doit plus pouvoir fermer la chaîne."""
    sortie = _esc("x' RETURN 1 //")
    assert "'" not in sortie.replace("\\'", ""), f"quote non échappé: {sortie}"


def test_esc_accepte_le_non_texte():
    assert _esc(42) == "42"
    assert _esc(None) == "None"


def test_label_refuse_ce_qui_n_est_pas_dans_la_liste():
    """Un label ne peut pas être paramétré : la liste blanche est la seule défense."""
    assert _label("Agent", NODE_TABLES) == "Agent"
    with pytest.raises(ValueError):
        _label("Agent) MATCH (x) DETACH DELETE x //", NODE_TABLES)


def test_num_neutralise_une_chaine_injectee():
    """Ces valeurs ne sont pas entre quotes : `_esc` ne les protégerait pas."""
    assert _num("5") == 5
    assert _num(2.5) == 2.5
    assert _num("1} ) DETACH DELETE n //", 0) == 0
    assert _num(None, 7) == 7
