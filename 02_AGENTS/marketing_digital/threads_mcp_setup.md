# Threads MCP — Guide d'installation + Routines PromptFlow

## Quel MCP choisir ?

Deux options selon ton niveau :

**Option A — Meta Platform MCP (recommandé, 57 outils)**
→ mcpmarket.com/server/meta-platform
→ Couvre Threads + Instagram + Analytics + DMs
→ Installation via le marketplace Cowork

**Option B — threads-mcp (open source, simple)**
→ github.com/tttn13/threads-mcp
→ Uniquement Threads, installation manuelle

**Ce guide utilise l'Option B** (plus simple à installer).

---

## Installation — Étape par étape

### 1. Créer une app Meta Developer

1. Va sur **developers.facebook.com/apps**
2. Clique "Créer une app"
3. Use case : **"Accéder à l'API Threads"**
4. Dans les paramètres, note :
   - `APP_ID` (Threads App ID)
   - `APP_SECRET` (Threads App Secret)
   - Configure une `REDIRECT_URI` (ex: `https://localhost:3000/callback`)

### 2. Récupérer ton Threads User ID

1. Va sur **threads.net** → Paramètres → Account → **User ID** visible dans l'URL du profil

### 3. Cloner et builder le MCP

```bash
# Dans ton terminal Windows (PowerShell)
git clone https://github.com/tttn13/threads-mcp
cd threads-mcp
npm install
npm run build
```

### 4. Configurer Claude Desktop

Ouvre `%APPDATA%\Claude\claude_desktop_config.json` et ajoute :

```json
{
  "mcpServers": {
    "threads-dev": {
      "command": "node",
      "args": ["C:/chemin/vers/threads-mcp/build/index.js"],
      "env": {
        "HOST": "https://graph.threads.net",
        "APP_ID": "TON_APP_ID",
        "APP_SECRET": "TON_APP_SECRET",
        "REDIRECT_URI": "https://localhost:3000/callback",
        "INITIAL_USER_ID": "TON_USER_ID",
        "PORT": "3000"
      }
    }
  }
}
```

### 5. Autoriser l'accès

Redémarre Claude Desktop. Dis-lui : **"Connecte mon compte Threads"** — il te guidera pour obtenir le long-lived token.

---

## Routines automatiques — Calendrier éditorial PromptFlow

### Fréquence recommandée : 2 posts/jour

| Heure | Type | Objectif |
|-------|------|----------|
| 08h00 | Post éducatif | Valeur gratuite → notoriété |
| 19h00 | Post conversion | Vente ebook / produit |

---

## Templates de posts — Ebook IA Agents

### Série 1 — "Le saviez-vous ?" (éducatif, 5 posts)

**Post 1 — Intro agents**
```
Un agent IA, c'est une IA qui :
→ Prend des décisions seule
→ Utilise des outils (email, Shopify, Google...)
→ Se souvient de ce qu'elle a appris
→ S'améliore à chaque cycle

La différence avec ChatGPT ? ChatGPT répond.
Un agent AGIT.

J'explique tout ça dans mon ebook gratuit ce week-end.
[lien]
```

**Post 2 — Mémoire**
```
Le truc que personne ne t'explique sur les agents IA :

Sans mémoire → ils repartent de zéro à chaque fois
Avec mémoire → ils capitalisent sur chaque tâche

Dans ma forge, Graphify stocke chaque finding.
OpenViking le retrouve quand c'est pertinent.

Résultat : le 50e cycle est 10x meilleur que le 1er.

C'est dans l'ebook ⬇️
[lien]
```

**Post 3 — Budget**
```
Combien ça coûte de faire tourner des agents IA ?

Sans optimisation : 200€+/mois
Avec OpenRouter + les bonnes règles : moins de 20€/mois

La règle des 80/20 :
80% des tâches → modèles GRATUITS
20% des tâches complexes → Claude/GPT

Je détaille ça au chapitre 6 de mon ebook.
27€. Lien dans la bio.
```

**Post 4 — Architecture**
```
Mon système d'agents en 5 blocs :

1. ForgeState — l'état partagé entre tous les agents
2. Agents spécialisés — chacun est expert dans son domaine
3. Mémoire persistante — Graphify + OpenViking
4. Jury qualité — les agents s'auto-évaluent
5. Orchestrateur — décide qui fait quoi

Ça tourne 24h/24 à ma place.

L'architecture complète → ebook "L'IA en Pratique"
promptflow.fr
```

**Post 5 — Résultat concret**
```
En 30 jours avec ma forge :

✅ 12 produits Shopify créés automatiquement
✅ 5 emails B2B rédigés et envoyés
✅ 1 landing page 450 lignes générée
✅ Coût total : < 5€ en tokens

Ce n'est pas de la théorie.
C'est ce que j'ai documenté dans l'ebook.

27€ → promptflow.fr
```

---

### Série 2 — Conversion directe (5 posts)

**Post 6 — Problème/Solution**
```
Tu utilises ChatGPT tous les jours.
Mais tu fais toujours le même travail en boucle.

Parce que ChatGPT ne se souvient pas.
Ne planifie pas.
Ne travaille pas seul.

Les agents IA font ça.

Mon ebook "L'IA en Pratique" t'explique comment construire le tien.
9 chapitres. 50 pages. Plan d'action 30 jours.

27€ → [lien]
```

**Post 7 — Urgence**
```
Prix de lancement : 27€ cette semaine seulement.

"L'IA en Pratique" — le guide pour construire tes agents IA

Après ça, le prix monte à 47€.

Pour qui : créateurs, entrepreneurs, freelances
Prérequis : aucun (zéro code requis)

Lien : [lien]
```

**Post 8 — Testimonial (à personnaliser après premières ventes)**
```
[Prénom] a lu l'ebook en 2h.

Le lendemain, il avait son premier agent qui tournait.

"Je pensais que c'était pour les devs.
Finalement, j'ai besoin que de Python de base."

C'est l'objectif du guide.

[lien]
```

**Post 9 — FAQ**
```
Questions fréquentes sur "L'IA en Pratique" :

Q: Il faut savoir coder ?
R: Non. Des exemples de code sont là pour comprendre, pas pour copier.

Q: Quel outil utiliser pour commencer ?
R: LangGraph (gratuit) + OpenRouter (gratuit)

Q: Combien de temps pour voir des résultats ?
R: 4 semaines si tu suis le plan d'action.

27€ → [lien dans bio]
```

**Post 10 — Urgence finale**
```
Dernier jour au prix de lancement.

"L'IA en Pratique" → 27€ jusqu'à ce soir minuit.

Demain : 47€.

9 chapitres sur la construction d'agents IA pour non-développeurs.
Livré immédiatement en PDF.

[lien]
```

---

## Routine automatique via la Forge

### Script de programmation (run_forge.py)

```bash
# Post du matin (éducatif) — 08h00
python run_forge.py --task "generate_threads_post type=educational day=1"

# Post du soir (conversion) — 19h00  
python run_forge.py --task "generate_threads_post type=conversion product=ebook_agents"
```

### Calendrier 30 jours

| Semaine | Thème | Posts |
|---------|-------|-------|
| S1 | Introduction aux agents IA | Posts 1-7 |
| S2 | Deep dive technique (simplifié) | Posts 8-14 |
| S3 | Cas d'usage + résultats | Posts 15-21 |
| S4 | Urgence + social proof | Posts 22-28 |

### Règles de la routine

1. **Jamais 2 posts de vente consécutifs** — alterner éducatif/conversion
2. **Toujours un CTA clair** — un seul lien par post
3. **Répondre à chaque commentaire dans les 2h** — l'algorithme Threads favorise les conversations
4. **Recycler les posts après 30 jours** — reformuler et republier les meilleurs
5. **Analyser les stats chaque lundi** — identifier les formats qui performent

---

## Intégration dans la Forge

Une fois le MCP installé, ajouter dans `agent_nodes.py` le nœud MARKETING pour qu'il poste automatiquement :

```python
# Dans marketing_node() — après génération du post
if threads_mcp_available():
    post_to_threads(content=generated_post, link=product_url)
    _caveman("MARKETING", "POST", "threads", platform="threads", chars=len(generated_post))
```

Le nœud MARKETING peut ainsi être déclenché depuis run_forge.py :
```bash
python run_forge.py --task "marketing_threads_daily"
```

