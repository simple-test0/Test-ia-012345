# Optimisations & flexibilité matérielle — notes de version

Ce document résume les changements apportés (performance, robustesse, support
multi-matériel) et les pistes d'amélioration restantes.

## 1. Socle matériel flexible (multi-vendeur)

Avant, toute la pile supposait NVIDIA/CUDA (`.to("cuda")` codé en dur, détection
NVIDIA-only). Désormais, un **socle device-agnostic** centralise la détection et
la sélection du device :

| Backend | Détection | Statut |
|---------|-----------|--------|
| NVIDIA CUDA | `torch.cuda` (`hip is None`) | ✅ complet (VRAM, util., driver) |
| AMD ROCm/HIP | `torch.cuda` (`torch.version.hip`) | ✅ vu comme `rocm` |
| Intel XPU | `torch.xpu` | ✅ (si build torch XPU) |
| Apple Silicon MPS | `torch.backends.mps` | ✅ mémoire unifiée |
| CPU | toujours présent | ✅ fallback |

- `backend/hardware/detector.py` — détection multi-vendeur, **mise en cache TTL
  (2 s)** (plus de `cpu_percent(interval=0.1)` bloquant à chaque requête), helpers
  `get_torch_device()`, `get_memory_budget_mb()`, `empty_accelerator_cache()`.
- `backend/hardware/recommender.py` — **tables `IMAGE_TIERS` / `AGENT_TIERS`
  pilotées par données** (ajouter un palier/modèle = une ligne), recommandations
  conscientes du backend (xformers NVIDIA-only sinon SDPA ; bf16 sur MPS/XPU ;
  `torch.compile` hors MPS) et de la mémoire unifiée.
- `pipeline_manager`, `worker`, `trainer` utilisent désormais le bon device/dtype
  automatiquement (générateur portable, AMP `torch.amp` non déprécié, etc.).

> **Pour ajouter du matériel/modèles** : éditer les tables du recommender ou
> appeler `model_registry.register_model(...)` au runtime.

## 2. Performance

- Détection matérielle **mise en cache** (les pages `/hardware/*` et chaque
  vérification VRAM interne ne relancent plus torch ni un échantillonnage CPU
  bloquant).
- **Pooling de connexions** Ollama : un seul `httpx.AsyncClient` keep-alive
  réutilisé (avant : une connexion TCP par appel).
- Cache LRU des pipelines configurable (`MAX_PIPELINES_LOADED`) + `torch.compile`
  optionnel (`ENABLE_TORCH_COMPILE`) appliqué au bon module (UNet ou DiT).
- `persistent_workers` sur les DataLoaders d'entraînement.

## 3. Robustesse ("moins capricieux")

- Plus de `except: pass` muets sur les chemins critiques → logs (`debug`/`warning`).
- Détection matérielle **ne lève jamais** : chaque sonde dégrade proprement.
- `requirements.txt` : correction du pin **`torchaudio` invalide (`0.19.1`)**,
  montée vers des versions cohérentes (FLUX/SD3.5), `onnxruntime` portable,
  ajout `sentencepiece`/`protobuf` (encodeurs T5), xformers rendu optionnel.
- Garde-fous API : rejet précoce des résolutions > `MAX_IMAGE_MEGAPIXELS` et
  message clair (403) pour les modèles *gated* sans `HUGGINGFACE_TOKEN`.
- `repo_id` de SD1.5 corrigé (`runwayml` supprimé → `stable-diffusion-v1-5/...`).
- CORS, device, seuils… déplacés en configuration (`.env`).

## 4. Modèles à jour (juin 2026)

- Image : ajout **FLUX.1 [schnell]/[dev]** et **SD3.5 Large** au registre.
- LLM : recommandations modernisées (Qwen2.5 / Qwen2.5-Coder, Llama 3.2/3.3,
  DeepSeek-R1, Gemma 2, Phi-4-mini) par palier de mémoire.

## 5. Petites configs & choix du modèle

- **Bugs de contrat WS corrigés** (l'app ne s'affichait pas correctement) :
  - Agent : `/agent/models` renvoie `{available, models[]}` ; le frontend
    attendait un tableau d'objets → `data[0].id` plantait. Corrigé.
  - Image : events `step.total` (vs `total_steps`) et `completed.images_b64`
    (vs `images`) ré-alignés ; position de file lue depuis la réponse POST.
- **Sélection de modèle réelle** :
  - L'image expose désormais `compatible` / `gated` / `min_vram_mb` / `family` et
    applique automatiquement les réglages recommandés du modèle (steps, CFG,
    résolution). Défaut = premier modèle **compatible**, modèles triés.
  - Résolutions proposées **bornées par le matériel** (jusqu'à `max_resolution`
    recommandé) + paliers plus bas (256/384) pour les petites machines.
- **Petites configs plus fluides** :
  - Preview latente (décodage VAE par étape) **désactivée sur CPU** et **throttlée**
    (≈8 aperçus/run) ailleurs — évite que la preview domine le temps de calcul.
  - `sd15` toujours disponible (min VRAM 0) ; offload CPU/séquentiel automatique.

## 6. Labs — du « zéro » au « renforcement » (GPU grand public 6-24 Go)

- **Transfer learning** (nouvelle architecture `pretrained`) : backbones ImageNet
  torchvision (MobileNetV3, EfficientNetV2-S, ConvNeXt-Tiny, ResNet-50, ViT-B/16)
  avec tête reconstruite et **freeze backbone** (entraînement tête seule) — la voie
  la plus rapide vers de bons résultats sur petite carte. Marquée « ★ recommended ».
- **Renforcement / fine-tuning** : bouton **Reinforce** sur tout run terminé →
  `POST /runs/{id}/finetune` crée un run **réinitialisé depuis le meilleur
  checkpoint** (LR réduit ×10, 5 epochs par défaut, dataset modifiable). Le trainer
  supporte `init_from` (warm-start, `strict=False`).
- **Techniques récentes accessibles depuis l'UI** : label smoothing, early stopping
  (patience), `torch.compile` (CUDA/XPU). Mixed precision bf16/fp16 device-aware.
- **Auto-tune pour mon GPU** : bouton qui pré-remplit batch size / grad-accum /
  precision / torch.compile depuis les recommandations matérielles.
- **Compatibilité visible** : chaque architecture indique son VRAM mini vs la carte
  détectée (badge ambre si ça dépasse), choix du backbone via menu (`select`).
- **Anti-« capricieux »** : message clair et actionnable en cas d'**OOM GPU**
  (réduire batch / augmenter grad-accum / baisser la résolution / activer fp16),
  cache mémoire vidé automatiquement.

## 7. Corrections d'audit

- **Entraînement débloqué** : sous-processus `daemon=False` (les workers DataLoader
  peuvent désormais démarrer), `num_workers` borné par les cœurs, terminaison
  propre des process au shutdown (`shutdown_all` + `atexit`/lifespan).
- **Transformer** : passe en classification par défaut (`num_classes=4`, min 2) ;
  `_make_dummy_dataset` garde-fou `max(num_classes, 2)`.
- **Contrat WS agent** : le planner émet `id` + `tool_name` → les cartes d'outils
  s'affichent et les résultats se rattachent.
- **Agent** : la session DB n'est plus tenue ouverte pendant le stream LLM
  (charge → ferme → run → ré-ouvre pour persister), client Ollama mutualisé,
  `system_prompt` injecté, `started_at` renseigné.
- **Upload datasets** : sanitisation du nom (anti path-traversal), écriture en
  streaming bornée par `MAX_UPLOAD_MB`, gestion d'erreur (status `error`), et
  persistance dans la requête (les `UploadFile` se ferment après).
- **Performance** : drain d'entraînement sur thread dédié (libère l'executor),
  `list_runs` paginé, `OneCycleLR` cohérent avec l'accumulation de gradient.
- **Compatibilité** : fallback explicite `FluxPipeline`/`StableDiffusion3Pipeline`
  si `AutoPipeline` ne résout pas la famille.
- **UI** : pas de reconnexion WS après fermeture propre, nouvelle session à
  « 0 messages », polling auto du statut dataset, events `info` du trainer
  affichés, erreurs de chargement remontées.

## 8. Installation débutant & reconnaissance matériel

- **Bug de reconnaissance corrigé** : les GPU rapportent un peu moins que leur
  VRAM nominale (8 Go → ~8188 Mo). Les breakpoints exacts faisaient tomber
  chaque carte un tier trop bas (une RTX 4060 Ti 8 Go était classée « 6-8 GB » →
  pas de SDXL complet, pas de `torch.compile`, agent limité au 3B). Ajout d'un
  headroom de ~4 % pour la **sélection de tier uniquement** (le dimensionnement
  batch/params garde la valeur réelle, conservatrice). Vérifié de 3 à 24 Go.
- **Installeur one-click** : `install.sh` (Linux/macOS) et `install.bat`
  (Windows, double-clic) — vérifient Python/Node, **détectent le GPU** et
  choisissent le wheel PyTorch (CUDA cu121 / ROCm / MPS / CPU), créent le venv,
  installent back+front, puis lancent l'optimisation.
- **Optimisation one-click** : `scripts/optimize.py` détecte le matériel, exécute
  le recommender et écrit un `backend/.env` optimisé (modèles, dtype,
  `torch.compile`, pipelines résidents, plafond mégapixels, tier LLM). Relançable
  après upgrade. Intégré aux scripts de démarrage au 1er lancement.
- **README** « démarrage rapide » pour débutants ; `start.bat` ajouté.

Exemple vérifié (RTX 4060 Ti 8 Go / 46 Go) → tier **High (8-12 GB)** : SDXL +
SDXL-Turbo + SD1.5, 1024px, fp16, xformers, `torch.compile` ; agents Llama3.1-8B
/ Qwen2.5-7B (q4) ; entraînement toutes architectures, batch auto, AMP fp16.

## 9. Revue complète du projet (corrections)

Audit transversal (3 passes : services backend, core/données, frontend).
Corrections retenues (faux positifs écartés : `created_at` présent, garde
clip-grad correcte, `_safe_name` OK, champ `tool_name` en trop inoffensif) :

- **Contrat image cassé (bloquant)** : `/image/jobs` renvoie `id`, le frontend
  utilisait `job_id` → clés/WS indéfinis. Normalisé côté frontend (`id → job_id`).
- **Progression image invisible** : la barre/preview n'apparaissait jamais (statut
  jamais `running`). Affichage dès `queued`, gestion de l'erreur, et **suppression
  du WebSocket dupliqué** sur le job actif.
- **Reconnexion WS fantôme** : `useWebSocket` se reconnectait après démontage
  volontaire (close ≠ 1000). Ajout d'un garde `closingRef` + respect de `enabled`.
- **Envois WS concurrents** : un burst de tokens d'agent pouvait lancer deux
  `send_json` simultanés sur le même socket (interdit par Starlette). Ajout d'un
  **lock par room** dans le ConnectionManager (nettoyé quand la room se vide).
- **Nettoyage** : requête dataset dupliquée supprimée dans `create_run`.

Vérifié : `compileall` backend OK, `tsc --noEmit` frontend OK.

## 10. Pistes restantes (suggestions)

- **Multi-GPU réel** : sharding / `device_map="balanced"` (accelerate) au lieu de
  n'utiliser que le GPU primaire ; agréger la VRAM pour les gros modèles.
- **pynvml** à la place de GPUtil pour une télémétrie NVIDIA plus fiable, et
  `amdsmi` / `xpu-smi` pour l'utilisation AMD/Intel.
- **Sandboxing** du `code_executor` (conteneur/`nsjail`/`RestrictedPython`) — le
  `subprocess` actuel n'est pas un vrai bac à sable.
- **Quantization** image (bitsandbytes / torchao FP8) + group offloading pour
  faire tenir FLUX/SD3.5 sous 12 Go.
- **Pagination/`count`** sur les endpoints de listing (sessions, runs) pour éviter
  de charger tout l'historique en mémoire.
- **Tests** : `pytest` sur le recommender (table-driven) et la détection mockée.
