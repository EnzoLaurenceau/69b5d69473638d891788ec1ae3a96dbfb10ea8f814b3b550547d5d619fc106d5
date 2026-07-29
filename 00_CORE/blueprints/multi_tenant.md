# Blueprint — Multi-tenant (option C)

> Décision : **option C — multi-tenant** (isolation stricte, quotas, découpage microservices).
> Ouvert le 2026-07-22 · board `05_STATE/kanban/forge_product_board.json` (W5-03)
> État : **socle posé et testé · migration non faite**

---

## 1. Le point de départ, mesuré

| Fait | Chiffre |
|---|---|
| Modules touchant `05_STATE` | **60** |
| Dont **écrivent** | **59** |
| Avec un verrou quelconque | **4** — et ce sont des `threading.Lock` |
| Fichiers d'état distincts | 23+ |

Un `threading.Lock` ne protège **qu'à l'intérieur d'un processus**. Entre deux workers,
deux requêtes ou deux utilisateurs, il ne garantit rien. L'état de la Forge est aujourd'hui
un ensemble de fichiers JSON écrits par 59 modules sans coordination : c'est utilisable en
mono-utilisateur local, et intenable dès le deuxième client.

## 2. Le principe retenu

**On n'obtient pas l'isolation en demandant à 59 modules d'y penser.** On l'obtient en
créant un passage obligé qui la rend structurelle :

```
59 modules ──► forge_store ──► [ forge_db : PG + Redis ]  (partagé, clés préfixées tenant)
                    │
                    └────────► 05_STATE/tenants/<tenant>/…  (repli, isolation physique)
                    ▲
              forge_tenant  ── contexte, fermé par défaut
```

`forge_store` résout le tenant à chaque appel et **refuse d'agir sans lui**. Un module qui
oublie le scope échoue bruyamment ; il n'écrit jamais dans l'espace d'un autre.

## 3. Décisions

| Sujet | Décision | Pourquoi |
|---|---|---|
| Identité | `contextvars`, **fermé par défaut** | Un défaut silencieux est pire qu'une panne. Sans tenant → `TenantError`. |
| Mono-utilisateur | `FORGE_SINGLE_TENANT=<id>` | Même politique que `FORGE_WEB_ALLOW_INSECURE` : l'insécurité est un **opt-in explicite**, jamais le défaut. |
| Threads | `propagate()` obligatoire | Les `contextvars` ne passent **pas** aux `ThreadPoolExecutor` — vérifié par test, contrairement à ce qu'on croit souvent. |
| Écriture | temporaire + `os.replace` | Le `write_text` direct (motif dominant du dépôt) laisse un JSON tronqué si le process meurt. |
| État corrompu | trace + `default`, **jamais d'écrasement** | Le motif `except: pass → return []` a effacé des historiques en silence (CRITICAL de l'audit). |
| Clés | validées, `..` et `/` interdits | Sans ça, une clé sort de l'espace du tenant. Double défense : validation + vérification du chemin résolu. |

## 4. Ce qui est fait

- `forge_tenant.py` — contexte, validation, `propagate()`. **ALL TESTS PASSED** (18 vérifications).
- `forge_store.py` — `put/get/append/read_lines/list_keys/delete/stats`, isolation, atomicité.
  **ALL TESTS PASSED**, dont : B ne voit rien de A · clés `../../etc` rejetées · corruption
  non écrasée · **200 écritures concurrentes sur 8 threads, 0 perdue**.

## 5. La migration des écrivains — ce qui a été fait, et ce que ça a appris

Le plan disait « migrer les 59 écrivains ». Mesuré au moment de le faire : **68 fichiers,
274 sites d'écriture**. Et surtout, la question était mal posée. Une bonne partie de cet
état n'appartient à personne en particulier — le catalogue d'outils, le registre des
tenants, la version du runtime. Le cloisonner serait **faux** : chaque client aurait son
propre registre de clients.

La question utile est donc *à qui appartient cet état ?*. Elle est tranchée une fois par
module, en clair, dans `00_CORE/tools/state_ownership.py` :

| Régime | Modules | Traitement |
|---|---|---|
| `tenant` | 32 | passe par `forge_store` — **24 migrés**, 8 listés avec leur raison |
| `platform` | 12 | reste global **volontairement** (identité, quotas, catalogue, version) |
| `exempt` | 24 | archive, tests, migrations ponctuelles, outillage opérateur |

**`state_path()` plutôt que `put/get/append`.** Porter 274 sites à l'API complète voulait
dire réécrire les entrées/sorties de 32 modules. Ce n'est pas ce qui manquait pour
expédier : ce qui manquait était **l'isolation**. `state_path()` la donne en changeant une
ligne par module, et le module garde son écriture. On achète l'isolation seule, sciemment ;
l'atomicité reste disponible via `put/append` pour le nouvel état.

**Outillé, pas manuel** — comme le blueprint l'exigeait : `00_CORE/tools/migrate_state_writers.py`
(dry-run par défaut, `py_compile` + restauration à la moindre casse). 24 modules migrés,
0 annulation, 64 tests verts.

**Un cliquet, sinon ça se referme.** `state_ownership.py --check` est une porte CI : un
nouvel écrivain non classé, ou un module `tenant` non migré hors liste connue, casse la
CI le jour où il est écrit. La liste des 8 restants ne peut que se vider.

**Ce qui prouve que ça marche** : `test_state_isolation.py` — deux tenants, le board de
tâches d'un client, vérifié qu'il ne fuit pas. Plus le mode transition (sans tenant →
chemin historique, l'existant ne casse pas) et le mode strict (CI → échec bruyant).

### Reste

1. **8 modules `tenant`** dont le chemin est dynamique, porté par une instance, ou SQLite
   (LangGraph). Listés avec leur raison dans `PENDING_ALLOWLIST`.
2. ~~Identité~~ — fait (W5-03b) : comptes, jetons hachés, middleware requête → tenant.
3. ~~Quotas~~ — fait (W5-03c) : stockage/requêtes/tokens, limites hors espace tenant.
4. **Microservices** — carte des bounded contexts faite (W5-03d), trading extrait (W5-03f/g).

## 6. Limite assumée

Le repli fichier isole physiquement par répertoire et suffit au mono-utilisateur et aux
tests. Il **ne remplace pas** PG+Redis pour du vrai multi-tenant concurrent multi-processus :
le verrou est un `threading.Lock` par clé, donc intra-processus. `forge_db` est branché en
miroir chaud.

Et `state_path()` ne donne **que le chemin** : les modules migrés gardent leur `write_text`,
donc pas d'écriture atomique chez eux. Deux processus qui écrivent le même fichier du même
tenant peuvent encore se marcher dessus. C'est acceptable pour un déploiement mono-processus
par tenant ; ça ne l'est pas pour du multi-worker. Ne pas vendre le contraire.
