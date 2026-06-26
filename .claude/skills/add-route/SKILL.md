---
name: add-route
description: Add a new FastAPI REST endpoint — creates route file, Pydantic schema, and wires the router in main.py
---

# Add REST Route: $ARGUMENTS

## Step 1 — Choose or create a router file

Existing routers in `backend/api/routes/`:
- `image_gen.py` → image generation, models, HF
- `agent.py` → sessions, tools, Ollama models
- `labs.py` → training, architectures, datasets
- `hardware.py` → GPU/CPU info

For a new domain, create `backend/api/routes/<domain>.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db

router = APIRouter(prefix="/<resource>", tags=["<tag>"])


@router.get("/", response_model=list[MySchema])
async def list_items(db: AsyncSession = Depends(get_db)):
    ...


@router.post("/", response_model=MySchema)
async def create_item(body: MyCreateSchema, db: AsyncSession = Depends(get_db)):
    ...
```

## Step 2 — Create schemas

**File**: `backend/schemas/<domain>.py`

```python
from pydantic import BaseModel


class MySchema(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}  # enables ORM mode


class MyCreateSchema(BaseModel):
    name: str
```

## Step 3 — Wire the router (new domain only)

In `backend/main.py` at line 63 (the `# CLAUDE: add new routers here` comment):

```python
from api.routes import <domain>
app.include_router(<domain>.router, prefix="/api/v1", dependencies=_auth)
```

## Step 4 — Verify

```bash
make test
cd backend && pytest tests/test_api_integration.py -v
```

## Rules
- Prefix `/api/v1/` is applied by `main.py` — don't duplicate it in the router
- Auth is applied globally via `dependencies=_auth` — don't add it per-route
- All routes must be `async`
- Errors: `raise HTTPException(status_code=404, detail="not found")`
- Body JSON: declare as a Pydantic schema parameter
