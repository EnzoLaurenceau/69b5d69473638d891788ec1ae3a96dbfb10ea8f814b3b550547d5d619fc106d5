# HANDOFF E4-01 — Wrappers audio (TTS, ffmpeg, MusicGen)

> **Ticket** : E4-01  
> **Epic** : E4 — AUDIO-PIPE  
> **Statut** : ✅ DONE  
> **Durée mesurée** : 0.2 j (estimé 3 j)  
> **Date** : 2026-07-29  
> **Dépendances** : aucune  

---

## Ce qui a changé en une phrase

La Forge n'avait **aucun code audio** (audit §9 : 0/10). Elle a maintenant trois
wrappers fonctionnels : TTS (edge-tts, 300+ voix), traitement audio (ffmpeg, 6
opérations), et génération musicale (MusicGen, stub prêt pour GPU).

---

## Livré

### `00_CORE/forge_agents/audio_pipe.py` (~430 lignes)

| Wrapper | Dispo | API |
|---------|-------|-----|
| **edge-tts** | ✅ installé | `tts_generate(text, voice)`, `tts_generate_stream()`, `tts_list_voices()` |
| **ffmpeg** | ✅ système | `audio_process.convert()`, `.normalize_lufs()`, `.mix()`, `.loop()`, `.trim()`, `.fade()` |
| **MusicGen** | ❌ stub | `music_available()`, `music_generate(prompt, duration)` — lève proprement |

Bonus : `probe(path)` → `AudioInfo` (durée, sample_rate, channels, codec).

### `test_e4_01_audio_pipe.py` (26 tests)

| Classe | Tests | Ce qu'elle vérifie |
|--------|-------|--------------------|
| TestAvailability | 5 | ffmpeg, ffprobe, tts, musicgen absent, generate lève |
| TestTTS | 7 | Fichier existe, format, durée, voix FR/EN, dictionnaires |
| TestProbe | 2 | AudioInfo, duration_str |
| TestConvert | 2 | WAV, OGG |
| TestNormalizeLUFS | 2 | Produit fichier, conserve durée |
| TestTrim | 1 | Réduit la durée |
| TestLoop | 1 | Augmente la durée |
| TestMix | 3 | 2 pistes, volumes différents, liste vide lève |
| TestFade | 1 | Produit fichier |
| TestAudioProcessInstance | 2 | Instance publique, méthodes présentes |

---

## Portes CI

| Porte | Résultat |
|-------|----------|
| `pytest test_e4_01_audio_pipe.py` | 26 passed (19.5s) |
| Suite complète | 443 passed, 42 skipped, 1 failed (pandas — préexistant) |
| Régression | 0 |

---

## Design decisions

### Pourquoi edge-tts et pas Coqui/Bark ?
- **Pas de GPU** requis (Coqui/Bark nécessitent un GPU)
- **300+ voix** dans 70+ langues
- **Gratuit** (Microsoft Edge, pas d'API key)
- **Async** natif (streaming possible pour les serveurs)
- Qualité suffisante pour du prototypage et du jeu indé

### Pourquoi un seul fichier ?
E4-02 (pipeline musique), E4-03 (SFX), E4-04 (gate audio) et E4-05 (KG↔audio)
importeront tous d'ici. Les wrappers individuels sont des détails d'implémentation.

### MusicGen = stub fonctionnel
Le modèle n'est pas installé (GPU + ~2 Go). L'API est prête : `music_available()`
renvoie False, `music_generate()` lève avec un message clair. Quand le GPU sera
disponible, il suffit de `pip install audiocraft`.

---

## Fichiers touchés

```
00_CORE/forge_agents/audio_pipe.py    # ~430 l. (nouveau module)
test_e4_01_audio_pipe.py              # 26 tests (nouveau)
pytest.ini                            # +1 ligne
```
