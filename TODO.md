# AI Studio — TODO (améliorations reportées)

Ces points ont été identifiés lors de la revue mais volontairement reportés pour
se concentrer d'abord sur les bloquants et le connecteur Hugging Face.

## Sécurité
- [ ] **`code_executor`** (`backend/services/agent/tools/code_executor.py`) : exécute du Python
      arbitraire sans sandbox, pilotable par le LLM via WebSocket. Le désactiver par défaut
      derrière un flag de configuration, ajouter des limites de ressources (CPU/mémoire),
      un timeout strict et un avertissement dans l'UI. Idéalement isoler (conteneur / `nsjail`).
- [ ] **`calculator`** (`backend/services/agent/tools/calculator.py`) : remplacer `eval` par un
      parseur d'expressions sûr (ex. `asteval`) pour éviter les abus type `(9**9)**9` (DoS CPU).
- [ ] **Auth / CSRF** : aucune authentification sur les routes REST ni les WebSockets. Sur une app
      locale, un site tiers ouvert dans le navigateur pourrait déclencher des actions.

## Fonctionnel
- [ ] **Sampler** : l'UI envoie un sampler (DPM++ 2M, Euler…) mais le worker
      (`backend/services/image_gen/worker.py`) ne configure aucun scheduler diffusers. Câbler le
      mapping sampler → scheduler, sinon le réglage est trompeur.
- [ ] **Labs / datasets** : le trainer (`backend/services/labs/trainer.py`) ne gère que les datasets
      au format `pixel_values`/`label` et retombe silencieusement sur des **données aléatoires**.
      Gérer plus de formats et signaler explicitement le repli côté UI.
- [ ] **Agent** : remplacer le parsing regex du bloc ```` ```tool ```` par le *function/tool calling
      natif* d'Ollama (plus robuste).
- [ ] **Téléchargement de modèles** : ajouter un pré-check d'espace disque (les modèles font 7–24 Go)
      et une vraie barre de progression (bridge `tqdm` de `snapshot_download`). Actuellement le suivi
      est un statut `downloading`/`ready`/`error` poll-é côté front.

## Qualité projet
- [ ] **README** : documenter l'installation, le lancement et les prérequis (Ollama, GPU, token HF).
- [ ] **Tests** (backend + frontend) et **CI**.
- [ ] **Dockerfile** / docker-compose pour un démarrage reproductible.
- [ ] **`start.sh`** : tourne actuellement `uvicorn --reload` (mode dev) ; prévoir un mode prod et
      vérifier/démarrer Ollama.
- [ ] Nettoyer les `try/except: pass` muets (preview VAE, GPUtil…) qui masquent les erreurs.
