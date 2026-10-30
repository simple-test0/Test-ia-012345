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
- [x] README, tests pytest (75+, API + entraînement réel en CI) + marqueur `heavy` pour l'e2e, CI GitHub Actions.
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

### Audit & amélioration (v1.1)
- [x] **Bugs bloquants corrigés** : page Agent qui ne détectait jamais Ollama (format de
      réponse mal lu), images générées jamais affichées sans recharger la page, upload de
      datasets cassé (fichiers fermés avant lecture) + faille path traversal, retry d'un
      téléchargement HF en erreur (violation d'unicité), prompt système ignoré,
      historique des conversations jamais rechargé, reconnexion WebSocket infinie après
      avoir quitté une page.
- [x] **Zéro blocage** : file de génération non bloquante (503 si pleine), outils / LoRA /
      sauvegarde d'images / arrêt d'entraînement / détection matérielle hors event loop,
      SQLite en WAL, tâches de fond référencées (plus de GC silencieux), reprise propre
      après redémarrage (jobs « en cours » marqués interrompus), détection des crashs
      d'entraînement.
- [x] **Perfs** : aperçus de diffusion par approximation latente (plus de décodage VAE à
      chaque étape), images servies par URL avec cache navigateur (fin des data-URL
      base64 dans le JSON), vignettes sur disque, GZip, pages chargées à la demande,
      graphes chargés à la demande, polling suspendu quand l'onglet est caché.
- [x] **Compatibilité** : Apple Silicon (MPS) pour la génération et l'entraînement, CPU sans
      GPU (fp32, pas d'offload CUDA), multiprocessing `spawn` (CUDA + macOS/Windows),
      requirements multi-plateformes (plus de `+cu121` forcé, xformers/onnxruntime-gpu
      conditionnels, greenlet sur ARM, peft pour les LoRA), choix auto de Python 3.10–3.12,
      `wss://` derrière HTTPS, Docker CPU/GPU.
- [x] **Confort** : réponses de l'agent en streaming + Markdown, annulation de génération,
      position dans la file, lightbox + téléchargement, réutilisation des réglages,
      réglages mémorisés, défauts par modèle, formats d'image, Ctrl+Entrée, upload et
      suppression de datasets, export ONNX/safetensors depuis l'UI, courbes de loss,
      messages d'erreur explicites, interface responsive (mobile/tablette), `start.sh`
      qui installe, ouvre le navigateur et ne réinstalle que si nécessaire, mode prod
      sur un seul port.

### v1.2
- [x] **img2img** : image source (glisser / coller / choisir, ou « utiliser comme source »
      depuis un résultat), force réglable, ratio conservé, migration Alembic. Validé de bout
      en bout sur CPU avec un mini-modèle SD (à valider sur GPU avec un vrai modèle).
- [x] **Bouton Stop** de l'agent (réponse partielle conservée, une réponse à la fois).
- [x] **Lanceur Windows** natif (`start.bat` / `start.ps1`).
- [x] **Arrêt instantané** (Ctrl+C) même pendant un téléchargement de modèle (107 s → 2 s).
- [x] Les tests ne téléchargent plus jamais de vrais modèles ; `alembic upgrade head`
      fonctionne sur une installation neuve ; plus de double session sur clic + Entrée rapides.

## ⏭️ Restant (nécessite un GPU pour être validé)
- [ ] **ControlNet** (pose/depth/canny) — pipeline + UI dédiés.
- [ ] Tests e2e exécutant réellement torch/diffusers (marqueur `heavy` déjà en place).
