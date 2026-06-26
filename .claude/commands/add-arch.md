# Ajouter une architecture Labs

Ajoute un nouveau type de réseau de neurones au module Labs. Arguments : `$ARGUMENTS` (nom de l'architecture).

## Étapes

1. **Créer** `backend/services/labs/architectures/<nom>.py` :

```python
import torch.nn as nn


def build_<nom>(config: dict) -> nn.Module:
    """Construit le modèle depuis un dict de config."""
    # Extraire les hyperparamètres avec des valeurs par défaut sûres
    hidden = config.get("hidden_size", 256)
    # ...
    return MyModel(hidden=hidden, ...)


class MyModel(nn.Module):
    def __init__(self, **kwargs):
        super().__init__()
        # définir les couches
        ...

    def forward(self, x):
        ...
```

2. **Enregistrer** dans `backend/services/labs/architecture_registry.py` :

```python
# Ajouter l'import en haut
from services.labs.architectures.<nom> import build_<nom>

# Ajouter dans ARCHITECTURE_REGISTRY
"<nom>": ArchitectureSpec(
    id="<nom>",
    name="<Nom complet>",
    description="<description concise — affichée dans l'UI>",
    builder=build_<nom>,
    default_config={
        "hidden_size": 256,
        # ...
    },
    task_types=["classification"],  # parmi: classification, nlp, detection
    min_vram_mb=512,               # VRAM minimale requise
    param_schema={
        "hidden_size": {"type": "integer", "min": 64, "max": 4096, "label": "Hidden size"},
        # "type" peut être: integer, float, boolean
    },
    tags=["<tag1>", "<tag2>"],
),
```

3. **Tester** :
```bash
cd backend && pytest tests/test_trainer_dataset.py -v
```

## Règles
- `build_<nom>(config)` doit fonctionner avec un `config` dict vide (defaults solides)
- `forward(x)` doit accepter des tenseurs standard PyTorch
- `min_vram_mb` = estimation conservative — préférer surestimer
- `param_schema` alimente le formulaire UI automatiquement — label obligatoire
- `task_types` filtre l'affichage par type de tâche dans l'UI
