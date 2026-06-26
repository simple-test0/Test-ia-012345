---
name: add-arch
description: Add a new PyTorch model architecture to the Labs training module — creates builder function and registers ArchitectureSpec
---

# Add Labs Architecture: $ARGUMENTS

## Step 1 — Create the architecture file

**File**: `backend/services/labs/architectures/<name>.py`

```python
import torch.nn as nn


def build_<name>(config: dict) -> nn.Module:
    """Build model from config dict — must work with empty config (safe defaults)."""
    return My<Name>(
        hidden_size=config.get("hidden_size", 256),
        num_classes=config.get("num_classes", 10),
    )


class My<Name>(nn.Module):
    def __init__(self, hidden_size: int = 256, num_classes: int = 10):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, num_classes),
        )

    def forward(self, x):
        return self.net(x)
```

## Step 2 — Register in architecture_registry.py

In `backend/services/labs/architecture_registry.py`:

**Add import** (top of file, after existing imports):
```python
from services.labs.architectures.<name> import build_<name>
```

**Add entry** at line 24 in `ARCHITECTURE_REGISTRY` (marked `# CLAUDE:`):
```python
"<name>": ArchitectureSpec(
    id="<name>",
    name="<Full display name>",
    description="<shown in UI — one sentence>",
    builder=build_<name>,
    default_config={
        "hidden_size": 256,
        "num_classes": 10,
    },
    task_types=["classification"],  # options: classification, nlp, detection
    min_vram_mb=512,                # conservative estimate — prefer overestimating
    param_schema={
        "hidden_size": {"type": "integer", "min": 64, "max": 4096, "label": "Hidden size"},
        "num_classes": {"type": "integer", "min": 2, "max": 10000, "label": "Output classes"},
        # type options: integer, float, boolean
    },
    tags=["<tag1>", "<tag2>"],
),
```

## Step 3 — Verify

```bash
make test
cd backend && pytest tests/test_trainer_dataset.py -v
```

## Rules
- `build_<name>(config)` must work with `config={}` — safe defaults are mandatory
- `forward(x)` must accept standard PyTorch tensors
- `min_vram_mb` is shown to users for hardware filtering — prefer overestimating
- `param_schema` auto-generates the UI form — `label` is required per field
- `task_types` drives UI filtering tabs
