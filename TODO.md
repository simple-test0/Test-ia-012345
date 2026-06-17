# AI Studio — TODO

## ✅ Done

### Sécurité
- [x] `code_executor` désactivé par défaut, `python -I`, timeout borné, limites
      mémoire **+ CPU** et taille de fichier (rlimits POSIX).
- [x] `calculator` : évaluateur AST sûr (anti-DoS exposant).
- [x] Auth token optionnelle (`API_TOKEN`) sur REST + WebSocket ; front via `VITE_API_TOKEN`.

### Fonctionnel
- [x] Sampler câblé → scheduler diffusers.
- [x] Tool-calling Ollama natif (repli regex).
- [x] Labs : warning « données aléatoires » + **support multi-formats de datasets**
      (pixel_values/image/img/input_ids/text + label/labels/target, images PIL → tenseurs).
- [x] Download HF : pré-check disque, taille estimée, **progression % byte-accurate**.
- [x] **LoRA** : adaptateur optionnel appliqué au pipeline (déchargé après chaque job).

### Qualité / Optimisation
- [x] README, tests pytest (24, sans torch) + marqueur `heavy` pour l'e2e, CI GitHub Actions.
- [x] Dockerfile backend & frontend + docker-compose (+ Ollama, proxy nginx).
- [x] `start.sh` mode prod + warning Ollama.
- [x] **Migrations DB via Alembic** (migration initiale générée + vérifiée) en plus de
      l'auto-migration légère de dev.
- [x] **Optimisations** : cache de détection hardware (TTL) + VRAM mémorisée (évite le
      `psutil.cpu_percent` bloquant à chaque requête) ; transport image unifié en `data:` URLs
      avec **vignettes JPEG** pour l'historique (payloads allégés).
- [x] Esthétique : système de **toasts** global, couleurs de focus unifiées (violet),
      champ LoRA dans l'UI.
- [x] Remplacement des `except: pass` muets par des logs debug.

## ⏭️ Restant (nécessite un GPU pour être validé)
- [ ] Génération **img2img** (upload d'image source) — back + UI à valider sur GPU.
- [ ] **ControlNet** (pose/depth/canny) — pipeline + UI dédiés.
- [ ] Tests e2e exécutant réellement torch/diffusers (marqueur `heavy` déjà en place).
