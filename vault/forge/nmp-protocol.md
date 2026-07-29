# 📡 NMP — Nano-Machine Protocol

> Protocole de communication inter-agents. Ultra-compact, machine-readable.

## Format

```
ACTION|SOURCE|TARGET|PAYLOAD
```

## Actions

### B2 Universal
| Action | Description |
|--------|-------------|
| INIT | Démarrer un agent |
| EXEC | Exécuter une tâche |
| OPT | Optimiser |
| SUCCESS | Tâche réussie |
| RETRY | Réessayer |
| ERR | Erreur |

### B1 Data
| Action | Description |
|--------|-------------|
| DATA_NEED | Besoin de données |
| DATA_ACK | Données reçues |
| DL_START | Début téléchargement |
| DL_DONE | Téléchargement terminé |
| DL_ERR | Erreur téléchargement |
| BOOST_NODE | Boost d'apprentissage |

### Audit
| Action | Description |
|--------|-------------|
| SCAN | Scanner |
| VULN | Vulnérabilité trouvée |
| OK | Tout va bien |
| DONE | Terminé |
| STATE | État |
| BUDGET | Budget tokens |
| ROUTE | Routage |

## Statuts

REQ, CONFIRMED, DENIED, FLUSH, SAVED, EXCEEDED, FREE, PAID

## Exemples

```
INIT|ORCHESTRATOR|RECON|scan:hackerone_X;type=IDOR
EXEC|EV_AGENT|hackerone_X|vuln=IDOR;score=8.5
DONE|CONFIRMED|task_001|score=9.2;tokens=1200
ERR|DENIED|download|reason=timeout
VULN|CONFIRMED|target_X|type=SSRF;severity=HIGH
DATA_NEED|RECON|HuggingFace|MIDWEIGHT|vuln_patterns
BOOST_NODE|EV_AGENT|EVOLVING|rule=always_check_IDOR
```

## Économie

| Communication | Tokens | Gain |
|---------------|--------|------|
| Verbose français | ~178 | baseline |
| NMP single message | ~123 | -31% |
| NMP inter-agent | ~36 | -80% |

## Règles

1. **TOUTE** communication inter-agent = NMP
2. Décodage français SEULEMENT à la présentation finale
3. Zéro wrapper conversationnel entre agents
4. Fragments positionnels séparés par pipes

## Implémentation

```python
# nanomachine.py
from .nanomachine import NANO_SYSTEM_PROMPT, invoke_gitnexus, parse_and_route

# Encoder
msg = f"INIT|ORCHESTRATOR|{agent_name}|{task_payload}"

# Décoder
action, source, target, payload = msg.split("|", 3)
```

## 🔗 Liens
- [[../forge/index|Forge Index]]
- [[ail-protocol|AIL Protocol]]
- [[a2a-protocol|A2A Protocol]]
