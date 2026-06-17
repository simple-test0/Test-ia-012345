# AI Studio — TODO

## ✅ Done

### Sécurité
- [x] **`code_executor`** désactivé par défaut (`ENABLE_CODE_EXECUTOR`), exécution isolée
      (`python -I`), timeout borné et limites mémoire/taille de fichier (POSIX).
- [x] **`calculator`** : `eval` remplacé par un évaluateur AST sûr (noms autorisés, garde
      anti-DoS sur les exposants).
- [x] **Auth / CSRF** : token partagé optionnel (`API_TOKEN`) sur REST (`X-API-Token`) et
      WebSocket (`?token=`) ; côté front via `VITE_API_TOKEN`. Header custom ⇒ non exploitable en CSRF.

### Fonctionnel
- [x] **Sampler** câblé : mapping sampler → scheduler diffusers (DPM++ 2M, Euler, Euler a, DDIM, LMS).
- [x] **Labs / données aléatoires** : événement `warning` explicite émis et affiché quand
      l'entraînement retombe sur des données générées.
- [x] **Tool-calling Ollama natif** : le planner utilise l'API `tools` d'Ollama (repli regex conservé).
- [x] **Pré-check espace disque** avant download HF + taille estimée + **progression %** (polling).

### Qualité projet
- [x] **README** complet.
- [x] **Tests** backend (pytest, sans torch) + **CI** GitHub Actions (backend + build frontend).
- [x] **Dockerfile** backend & frontend + **docker-compose** (backend, frontend, Ollama).
- [x] **`start.sh`** : mode prod (`MODE=prod`, sans `--reload`) + warning si Ollama injoignable.
- [x] **Auto-migration légère** SQLite (ajout de colonnes manquantes au démarrage).
- [x] Remplacement des `except: pass` muets (preview VAE, GPUtil) par des logs debug.

## ⏭️ Restant (améliorations futures)
- [ ] Migrations DB robustes via Alembic (l'auto-migration actuelle est minimaliste, SQLite only).
- [ ] Barre de progression de download exacte via un vrai bridge `tqdm` (actuellement estimée par
      la taille du dossier vs métadonnées HF).
- [ ] Labs : support de davantage de formats de datasets (au-delà de `pixel_values`/`label`).
- [ ] Sandboxing renforcé de `code_executor` (conteneur / `nsjail`) au-delà des rlimits POSIX.
- [ ] Tests end-to-end incluant torch/diffusers (lourds — exclus de la CI légère).
- [ ] Image generation : ControlNet / img2img / LoRA.
