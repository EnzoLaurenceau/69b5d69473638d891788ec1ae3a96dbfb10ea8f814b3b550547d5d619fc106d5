# HANDOFF E3-01 — ArtifactType étendu pour les assets RPG

> **Ticket** : E3-01  
> **Epic** : E3 — ASSET-PIPE  
> **Statut** : ✅ DONE  
> **Durée mesurée** : 0.15 j (estimé 1 j)  
> **Date** : 2026-07-29  
> **Dépendances** : aucune  

---

## Ce qui a changé en une phrase

Le Harness connaissait 10 types d'artefacts web/dev — et aucun type jeu. Un PNG
« concept art » validé comme CODE sortait 100/100 parce que les gates CODE ne
s'appliquent pas à un PNG. Le score était aveugle, pas bon. Il y a maintenant
7 types jeu + des gates réels (existence, format, taille).

---

## Livré

### `00_CORE/forge_agents/harness_engine.py` (+190 lignes)

| Ajout | Détail |
|-------|--------|
| 7 `ArtifactType` | CONCEPT, SPRITE, TEXTURE, MODEL_3D, RIG, ANIM, VFX |
| 7 entrées `GATES` | 3-4 gates par type (existence, format, taille, ±dimensions) |
| 10 `_check_*` réels | `_check_asset_file_exists`, `_check_file_size`, `_check_image_format`, `_check_sprite_format`, `_check_texture_format`, `_check_model_format`, `_check_anim_format`, `_check_vfx_format`, `_check_image_dimensions`, `_check_power_of_two` |
| 6 sets de formats | `_IMAGE_FORMATS`, `_SPRITE_FORMATS`, `_TEXTURE_FORMATS`, `_MODEL_FORMATS`, `_ANIM_FORMATS`, `_VFX_FORMATS` |

### `00_CORE/forge_agents/artifact_quality.py` (+5 lignes)

Extensions jeu ajoutées au mapping `EXTENSIONS` (→ `asset`) : `.fbx`, `.obj`, `.gltf`, `.glb`, `.blend`, `.dae`, `.3ds`, `.stl`, `.psd`, `.tiff`, `.aseprite`, `.ase`, `.bvh`, `.anim`, `.shader`, `.hlsl`, `.glsl`, `.vfx`, `.vfxgraph`, `.particle`.

### `test_e3_01_asset_types.py` (60 tests)

| Classe | Tests | Ce qu'elle vérifie |
|--------|-------|--------------------|
| TestEnum | 9 | Valeurs, total 17, JSON serializable |
| TestGatesExist | 21 | Chaque type a ≥2 gates, un gate existence, un gate file_size |
| TestAssetFileExists | 2 | Fichier existant/manquant |
| TestFileSize | 2 | Sous/dépasse le seuil |
| TestFormatChecks | 10 | Accepte/rejette les bonnes/mauvaises extensions |
| TestValidate | 4 | Pipeline complet, score, grade |
| TestExtensionMapping | 12 | Extensions mappées vers 'asset' |

---

## Portes CI

| Porte | Résultat |
|-------|----------|
| `pytest test_e3_01_asset_types.py` | 60 passed (1.68s) |
| Suite complète | 399 passed, 42 skipped, 1 failed (pandas — préexistant) |
| Régression | 0 |

---

## Ce que les 7 types couvrent

```
CONCEPT  → concept art, mood boards         (PNG/JPG/WebP/PSD, ≥512×512, <50 MB)
SPRITE   → 2D sprites, tilesets, atlas      (PNG/WebP, power-of-two, <5 MB)
TEXTURE  → PBR, normal maps, UV             (PNG/TGA/JPG, power-of-two, <20 MB)
MODEL_3D → meshes                           (FBX/OBJ/glTF/Blend, <100 MB)
RIG      → skeleton + weights               (FBX/Blend, <50 MB)
ANIM     → animation clips                  (FBX/BVH/glTF, <20 MB)
VFX      → particles, shaders, effects      (shader/particle/config, <10 MB)
```

---

## Ce qui vient après

- **E3-02** : Style-lock — bible visuelle dans le World-KG, injectée dans chaque génération
- **E3-05** : Gates avancés (cohérence style, lisibilité, budget polygones)
- **E3-06** : Cache d'assets par fingerprint sémantique
- **E3-07** : Gate copyright/licence (branche `world_canon.guard()`)

---

## Fichiers touchés

```
00_CORE/forge_agents/harness_engine.py    # +190 l. (types + gates + checks)
00_CORE/forge_agents/artifact_quality.py  # +5 l. (extensions mapping)
test_e3_01_asset_types.py                 # 60 tests (nouveau)
pytest.ini                                # +1 ligne
```
