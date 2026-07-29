# 🧬 TEMPLATE UNIVERSEL — Tous les Agents de la Forge
> Chaque agent DOIT implémenter ce cycle. Sans exception.
> MiroFish = jury interne · Graphify = mémoire persistante · Auto-complexification = évolution

---

## RÈGLE FONDAMENTALE

Un agent de la Forge n'est pas un outil statique.
Il est un **système vivant** qui :
1. **Pense** avec MiroFish (jury interne multi-personas)
2. **Mémorise** avec Graphify (graph persistant entre sessions)
3. **Évolue** avec l'algorithme d'auto-complexification

Sans ces 3 éléments, c'est un script, pas un agent.

---

## STRUCTURE OBLIGATOIRE DE TOUT AGENT

```
AGENT_<NOM>/
├── config.json          ← paramètres + niveau actuel
├── personas.json        ← jury MiroFish interne (3-5 personas spécialisés)
├── memory.md            ← résumé sessions précédentes (lu depuis graphify)
├── scoring_rubric.md    ← critères d'auto-évaluation
└── AGENT_<NOM>.md       ← logique principale
```

---

## CYCLE D'EXÉCUTION UNIVERSEL (à implémenter dans chaque agent)

```
╔══════════════════════════════════════════════════════╗
║  BOUCLE AGENT — v1.0                                 ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  [INIT]                                              ║
║    → graphify_query("agent=<nom> last_session")      ║
║    → Charger checkpoint agent depuis 05_STATE/       ║
║    → CAVEMAN ON                                      ║
║                                                      ║
║  [EXECUTE]                                           ║
║    → Effectuer la tâche principale                   ║
║    → Produire des outputs/findings                   ║
║                                                      ║
║  [JURY INTERNE — MiroFish]                           ║
║    → Seeder le jury avec les outputs (≤500 tokens)   ║
║    → N personas évaluent selon le scoring_rubric     ║
║    → JURY VERDICT score consensus suggestion         ║
║                                                      ║
║  [STORE — Graphify]                                  ║
║    → graphify_index(findings validés)                ║
║    → graphify_index(règles apprises)                 ║
║    → Mettre à jour checkpoint agent                  ║
║                                                      ║
║  [AUTO-COMPLEXIFICATION]                             ║
║    → Comparer cycle N vs N-1                         ║
║    → Si quality_delta > 0.1 → LEVEL_UP               ║
║    → Si token_delta > 0 sans gain → ROLLBACK         ║
║    → Intégrer suggestions jury si confidence > 0.7   ║
║                                                      ║
║  [REPORT]                                            ║
║    → 1 ligne caveman vers Orchestrateur              ║
║    → CAVEMAN OFF si rapport final                    ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
```

---

## JURY MIROFISH INTERNE — Format personas spécialisés

Chaque agent a son propre jury adapté à sa mission.
Format personas.json :

```json
{
  "agent": "<nom>",
  "jury_size": 3,
  "personas": [
    {
      "id": "domain_expert",
      "role": "Expert du domaine <métier>",
      "challenge": "La décision est-elle techniquement/méthodologiquement correcte ?",
      "weight": 1.3
    },
    {
      "id": "user_proxy",
      "role": "Représentant de l'utilisateur final",
      "challenge": "Est-ce que ça résout vraiment le problème de l'user ?",
      "weight": 1.0
    },
    {
      "id": "token_optimizer",
      "role": "Gardien de l'efficacité tokens",
      "challenge": "Peut-on obtenir le même résultat avec moins de tokens ?",
      "weight": 0.9
    }
  ],
  "consensus_min": 0.65,
  "seed_format": "JURY SEED agent=<nom> output=<id> task=<slug> cycle=<N>"
}
```

---

## MÉMOIRE GRAPHIFY — Ce que chaque agent indexe

```python
# Après chaque session réussie
graphify_index(f"""
## AGENT-{NOM}-SESSION-{date}
Cycle: {N}
Task: {task_slug}
Output_quality: {jury_score}
Key_learning: {apprentissage_principal}
Rule_applied: {règle_utilisée}
New_rule: {nouvelle_règle_si_applicable}
Token_savings: {ratio}x vs cycle précédent
Next_focus: {prochain_sujet}
""")

# Après chaque règle validée par jury
graphify_index(f"""
## RULE-{agent}-{id}
Agent: {NOM}
Rule: {texte_règle}
Confidence: {jury_confidence}
Applied_since: cycle_{N}
Status: active
""")
```

---

## CHECKPOINT AGENT — Structure 05_STATE/agents/<nom>.json

```json
{
  "agent": "<nom>",
  "level": "L1",
  "cycle_count": 0,
  "quality_history": [],
  "token_savings_ratio": 1.0,
  "active_rules": [],
  "killed_rules": [],
  "jury_suggestions_applied": 0,
  "last_session": null,
  "graph_nodes_contributed": 0
}
```

---

## CAVEMAN OUTPUT STANDARD

```
<AGENT> DONE task=<slug> quality=<0-1> tokens_saved=<Nx> jury_consensus=<0-1> level=<L1|L2|L3>
<AGENT> LEARN rule="<nouvelle_règle>" confidence=<0-1> cycle=<N>
<AGENT> EVOLVE level=<L1→L2> reason="<quality_gain=X>"
<AGENT> ROLLBACK cycle=<N> reason="<regression>"
```

---

## 🎯 FABLE 5 BEHAVIOR RULES (OBLIGATOIRE)

Chaque agent dynamique DOIT respecter ces règles lors de l'exécution de sa tâche :

1. **Standalone Artifacts** : Si l'output (code, texte, données) est destiné à être utilisé hors conversation et dépasse 10 lignes, il DOIT être écrit dans un fichier (`create_file`). Ne pas polluer le chat.
2. **Compression d'Output** : Pour économiser les tokens, toujours partager les chemins de fichiers générés directement (sans "Voici le fichier demandé..." ni d'explications superflues/post-ambules).
3. **SKILLS First** : Lire les fichiers `SKILL.md` ou la documentation d'outils correspondants *avant* d'écrire du code complexe. (Cela importe la connaissance sans surencombrer ce prompt).
4. **Recherche & Copyright** : Max 1 citation par source (< 15 mots). Reformulation obligatoire. Forcer la recherche web pour des faits ou états actuels susceptibles de changer.
5. **Persistance (Non-Browser)** : Ne jamais utiliser `localStorage`/`sessionStorage` dans les UIs générées. Utiliser la base de données de l'application ou l'index GitNexus de La Forge pour stocker l'état.
6. **Délégation Open Source** : Ne pas réinventer la roue. Chercher activement (via recherche standard pour économiser les tokens) un dépôt GitHub ou un outil logiciel tiers existant pour réaliser la tâche au lieu de coder une logique de zéro. Une fois trouvé, créer un micro-script (wrapper) réutilisable appelant cet outil pour les prochaines fois. OBLIGATOIRE : exécuter ensuite `npx gitnexus analyze` pour mettre à jour l'index de La Forge.
7. **Chatbot Adaptation** : Si une application web générée nécessite un chatbot IA, ses instructions système et son persona doivent être rigoureusement adaptés aux besoins, à l'image de marque et au domaine du client (par exemple, un système de mots-clés trilingue ou un prompt spécifique) afin de garantir une expérience utilisateur pertinente. De plus, le chatbot doit automatiquement s'adapter et parler la langue active sélectionnée par l'utilisateur (mise à jour automatique des messages d'accueil, placeholders, boutons d'aide, et détection de mots-clés adaptés à la langue active).
8. **Interactive Maps (OpenStreetMap)** : Si une application web générée affiche des coordonnées physiques ou l'adresse d'un commerce, elle DOIT obligatoirement inclure une carte interactive utilisant OpenStreetMap (via la bibliothèque Leaflet.js, stylisée de préférence avec les tuiles CartoDB Voyager) pour géolocaliser le commerce précisément.


