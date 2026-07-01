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
- [x] Génération **img2img** : upload d'image source + slider strength, pipeline
      `AutoPipelineForImage2Image` (réutilise les poids du pipeline chargé via `from_pipe`).
- [x] **ControlNet** (canny/depth/pose) pour SD 1.5 et SDXL : upload d'image de contrôle,
      pré-traitement canny local (PIL, sans cv2) ; depth/pose attendent une carte déjà calculée.
- [x] **Stabilisation** : récupération des jobs orphelins au démarrage (queue en mémoire),
      correction du `NameError` masquant l'erreur réelle quand le chargement du pipeline échoue,
      référence forte sur les tâches de téléchargement HF (risque de GC en plein download),
      gestion des événements WS `started`/`error` côté front (jobs qui restaient « queued »/
      « running » pour toujours), messages d'erreur backend affichés dans l'UI.

## ⏭️ Restant (nécessite un GPU pour être validé)
- [ ] Valider img2img + ControlNet sur GPU (le code est en place, testé sans torch).
- [ ] Tests e2e exécutant réellement torch/diffusers (marqueur `heavy` déjà en place).
