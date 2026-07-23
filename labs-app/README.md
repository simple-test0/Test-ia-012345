# AI Studio — Labs (application autonome)

Application d'entraînement de réseaux de neurones, lancée indépendamment
de l'application principale AI Studio.

## Démarrage

```
labs-app\start-labs.bat     → http://localhost:8100
labs-app\stop-labs.bat      → arrêt (ou bouton ⏻ dans l'interface)
```

Aucune installation supplémentaire : l'app réutilise l'environnement Python
du backend (`backend/.venv`). La base de données dédiée (`data/db/labs.db`)
est **créée automatiquement au premier démarrage** (SQLAlchemy `create_all`
+ migrations légères), il n'y a rien à configurer.

## Fonctionnalités

- **Entraînements** : 5 architectures (CNN, RNN, LSTM, GRU, Transformer, ViT),
  métriques en direct (WebSocket), pause/reprise/arrêt, suppression,
  export ONNX et safetensors.
- **Options maximales** : 7 optimiseurs (AdamW, Adam, SGD±Nesterov, NAdam,
  Adamax, Adagrad, RMSprop), 8 schedulers (cosine, warmup+cosine, one-cycle,
  linear, step, exponential, plateau, none), label smoothing, gradient
  clipping, accumulation de gradient, précision mixte fp16, early stopping,
  seed reproductible, rétention configurable des checkpoints.
- **Tokenisation** : entraînement de tokenizers personnalisés sur vos datasets
  (BPE byte-level, WordPiece, Unigram, Word-level, caractères), terrain
  d'essai interactif, intégration directe aux runs NLP (le vocabulaire du
  modèle s'aligne automatiquement sur celui du tokenizer).
- **Datasets** : téléchargement Hugging Face ou import de fichiers
  (.txt, .csv, .tsv, .json, .jsonl).
- **Matériel** : détection GPU/RAM/CPU + recommandations d'entraînement.
- **Console** : logs serveur en direct.

## Choix techniques (et pourquoi)

Recherche effectuée en juillet 2026 — critères : gratuit, local-first, léger.

| Besoin | Techno retenue | Pourquoi |
|---|---|---|
| Tokenisation | **HF `tokenizers`** (Rust) | Seule lib majeure qui *entraîne* des tokenizers (tiktoken ne fait qu'encoder) ; déjà installée via `transformers` → coût zéro |
| Suivi des métriques | **SQLite + WebSocket** | Même approche local-first que Trackio (Hugging Face, 2026) ; aucune dépendance à ajouter |
| Interface | **HTML/CSS/JS vanilla** | Zéro build, zéro npm, servie par FastAPI ; démarre en ~2 s |
| Base de données | **SQLite (WAL)** auto-créée | Un fichier, aucune installation, lecteurs+écrivain simultanés |
| Entraînement | **PyTorch en subprocess** | Isolation du GIL, pause/resume/stop, déjà éprouvé dans le backend |

Bonnes pratiques appliquées (issues de la recherche) :
- tailles de vocabulaire **divisibles par 128** (meilleur débit GPU) — le champ
  vocab de l'UI incrémente par 128 ;
- tokens spéciaux standards `[PAD] [UNK] [CLS] [SEP] [MASK]`, personnalisables ;
- `min_frequency` réglable pour les petits corpus ;
- presets de vocab raisonnables (1k–32k) pour des modèles locaux.

Sources principales :
- [Comparatif tiktoken / SentencePiece / HF Tokenizers (2026)](https://www.bestaiweb.ai/how-to-train-and-choose-a-custom-tokenizer-with-tiktoken-sentencepiece-and-hf-tokenizers-in-2026/)
- [tiktoken vs HuggingFace Tokenizers — benchmark](https://machinelearningplus.com/gen-ai/tiktoken-vs-huggingface-tokenizers/)
- [Entraîner BPE/WordPiece/Unigram avec Hugging Face](https://www.freecodecamp.org/news/train-algorithms-from-scratch-with-hugging-face/)
- [Getting the most out of your tokenizer (arXiv 2402.01035)](https://arxiv.org/pdf/2402.01035)
- [Tokenizer Choice For LLM Training (arXiv 2310.08754)](https://arxiv.org/pdf/2310.08754)
- [Trackio — suivi d'expériences local-first (Hugging Face)](https://github.com/gradio-app/trackio)

## Architecture

```
labs-app/
  main.py           serveur FastAPI dédié (port 8100)
  static/           interface (index.html, app.js, style.css)
  start-labs.bat    lanceur avec supervision auto
  stop-labs.bat     arrêt propre
```

Le serveur importe les services du backend (`backend/services/labs/*`) :
une seule implémentation de l'entraînement, deux applications. Les dossiers
de données (datasets, tokenizers, modèles) sont partagés avec l'app
principale ; seule la base d'enregistrements est séparée (`labs.db` vs
`app.db`), pour que les deux apps restent indépendantes.
