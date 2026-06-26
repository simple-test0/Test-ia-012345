# Ajouter une route REST

Ajoute un endpoint FastAPI au backend. Arguments : `$ARGUMENTS` (ex: `GET /api/v1/models/stats`).

## Étapes

1. **Choisir le bon fichier** dans `backend/api/routes/` :
   - `image_gen.py` → génération d'images
   - `agent.py` → sessions agent / historique
   - `labs.py` → entraînement, architectures, datasets
   - `hardware.py` → infos GPU/CPU
   - Nouveau domaine → créer `backend/api/routes/<domaine>.py` et l'enregistrer dans `main.py`

2. **Template de route** :

```python
from fastapi import APIRouter, Depends, HTTPException
from core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["<domaine>"])

@router.get("/<ressource>", response_model=<SchemaResponse>)
async def get_ressource(db: AsyncSession = Depends(get_db)):
    ...
```

3. **Créer les schemas** dans `backend/schemas/<domaine>.py` :

```python
from pydantic import BaseModel

class <Nom>Response(BaseModel):
    id: int
    # ...
    model_config = {"from_attributes": True}
```

4. **Si nouveau router** — ajouter dans `backend/main.py` :

```python
from api.routes import <domaine>
app.include_router(<domaine>.router, prefix="/api/v1", dependencies=_auth)
```

5. **Tester** :
```bash
cd backend && pytest tests/test_api_integration.py -v
```

## Conventions
- Toutes les routes sont async
- Préfixe `/api/v1/` appliqué par `main.py` — ne pas le dupliquer dans le router
- Auth appliquée globalement via `dependencies=_auth` dans `main.py`
- Erreurs → `raise HTTPException(status_code=..., detail="...")`
- Body JSON → schéma Pydantic en paramètre de la fonction (`body: MonSchema`)
