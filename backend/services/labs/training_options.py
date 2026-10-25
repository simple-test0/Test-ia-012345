"""Schema of every supported training option — single source of truth for UIs."""

TRAINING_OPTIONS = {
    "epochs": {
        "type": "integer", "min": 1, "max": 1000, "default": 10,
        "label": "Epochs", "group": "base",
        "help": "Nombre de passages complets sur le dataset.",
    },
    "batch_size": {
        "type": "integer", "min": 1, "max": 1024, "default": 16,
        "label": "Batch size", "group": "base",
        "help": "Exemples par lot. Plus grand = plus rapide mais plus de VRAM.",
    },
    "learning_rate": {
        "type": "float", "min": 1e-6, "max": 1.0, "default": 3e-4, "step": 1e-5,
        "label": "Learning rate", "group": "base",
        "help": "Taille des pas d'optimisation. 3e-4 est un bon départ pour AdamW.",
    },
    "val_split": {
        "type": "float", "min": 0.05, "max": 0.5, "default": 0.2, "step": 0.05,
        "label": "Part de validation", "group": "base",
        "help": "Fraction du dataset réservée à la validation.",
    },
    "seed": {
        "type": "integer", "min": 0, "max": 999999, "default": 42,
        "label": "Seed", "group": "base",
        "help": "Graine aléatoire pour des runs reproductibles.",
    },
    "optimizer": {
        "type": "enum", "default": "adamw",
        "choices": ["adamw", "adam", "sgd", "nadam", "adamax", "adagrad", "rmsprop"],
        "label": "Optimizer", "group": "optimizer",
        "help": "AdamW est le standard actuel. SGD+momentum reste solide en vision.",
    },
    "weight_decay": {
        "type": "float", "min": 0.0, "max": 0.3, "default": 1e-4, "step": 1e-4,
        "label": "Weight decay", "group": "optimizer",
        "help": "Régularisation L2 découplée (AdamW).",
    },
    "momentum": {
        "type": "float", "min": 0.0, "max": 0.99, "default": 0.9, "step": 0.01,
        "label": "Momentum (SGD)", "group": "optimizer",
        "help": "Inertie du gradient — utilisé uniquement par SGD.",
    },
    "nesterov": {
        "type": "boolean", "default": False,
        "label": "Nesterov (SGD)", "group": "optimizer",
        "help": "Variante anticipée du momentum.",
    },
    "lr_scheduler": {
        "type": "enum", "default": "cosine",
        "choices": ["cosine", "warmup_cosine", "onecycle", "linear", "step",
                    "exponential", "plateau", "none"],
        "label": "LR scheduler", "group": "scheduler",
        "help": "Évolution du learning rate au fil des epochs.",
    },
    "warmup_epochs": {
        "type": "integer", "min": 0, "max": 50, "default": 0,
        "label": "Warmup (epochs)", "group": "scheduler",
        "help": "Montée progressive du LR — utilisé par warmup_cosine.",
    },
    "step_size": {
        "type": "integer", "min": 1, "max": 100, "default": 5,
        "label": "Step size", "group": "scheduler",
        "help": "Période de décroissance — scheduler step.",
    },
    "gamma": {
        "type": "float", "min": 0.01, "max": 0.99, "default": 0.5, "step": 0.01,
        "label": "Gamma / facteur", "group": "scheduler",
        "help": "Facteur multiplicatif — schedulers step, exponential et plateau.",
    },
    "plateau_patience": {
        "type": "integer", "min": 1, "max": 20, "default": 2,
        "label": "Patience plateau", "group": "scheduler",
        "help": "Epochs sans amélioration avant de réduire le LR (plateau).",
    },
    "label_smoothing": {
        "type": "float", "min": 0.0, "max": 0.3, "default": 0.0, "step": 0.01,
        "label": "Label smoothing", "group": "regularization",
        "help": "Adoucit les cibles — limite la sur-confiance du modèle.",
    },
    "gradient_clip_norm": {
        "type": "float", "min": 0.0, "max": 10.0, "default": 1.0, "step": 0.1,
        "label": "Gradient clipping", "group": "regularization",
        "help": "Norme max des gradients (0 = désactivé). Stabilise RNN/Transformers.",
    },
    "gradient_accumulation_steps": {
        "type": "integer", "min": 1, "max": 64, "default": 1,
        "label": "Accumulation de gradient", "group": "performance",
        "help": "Simule un batch N fois plus grand sans plus de VRAM.",
    },
    "use_mixed_precision": {
        "type": "enum", "default": "fp16", "choices": ["fp16", "no"],
        "label": "Précision mixte", "group": "performance",
        "help": "fp16 sur GPU: ~2x plus rapide, moitié moins de VRAM.",
    },
    "early_stopping_patience": {
        "type": "integer", "min": 0, "max": 100, "default": 0,
        "label": "Early stopping (patience)", "group": "early_stopping",
        "help": "Stoppe si la val loss stagne N epochs (0 = désactivé).",
    },
    "early_stopping_min_delta": {
        "type": "float", "min": 0.0, "max": 1.0, "default": 0.0, "step": 0.001,
        "label": "Delta minimal", "group": "early_stopping",
        "help": "Amélioration minimale pour compter comme un progrès.",
    },
    "keep_last_checkpoints": {
        "type": "integer", "min": 0, "max": 100, "default": 3,
        "label": "Checkpoints conservés", "group": "checkpoints",
        "help": "Nombre de checkpoints récents gardés sur disque (le meilleur est toujours conservé, 0 = tout garder).",
    },
}

OPTION_GROUPS = {
    "base": "Essentiels",
    "optimizer": "Optimiseur",
    "scheduler": "Learning rate",
    "regularization": "Régularisation",
    "performance": "Performance",
    "early_stopping": "Arrêt anticipé",
    "checkpoints": "Checkpoints",
}
