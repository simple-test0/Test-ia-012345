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

## 5. Pistes restantes (suggestions)

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
