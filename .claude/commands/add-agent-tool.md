# Ajouter un outil agent Ollama

Crée un nouvel outil pour l'agent IA. Arguments : `$ARGUMENTS` (nom de l'outil souhaité).

## Étapes

1. **Créer** `backend/services/agent/tools/<nom>.py` avec ce template exact :

```python
from services.agent.tool_registry import register_tool


@register_tool(
    name="<nom>",
    description="<description courte et précise de ce que fait l'outil>",
    parameters={
        "type": "object",
        "properties": {
            "<param1>": {"type": "string", "description": "<description>"},
        },
        "required": ["<param1>"],
    },
)
async def <nom>(<param1>: str) -> str:
    # implémentation
    ...
```

2. **Enregistrer** dans `backend/main.py`, à l'intérieur du bloc `lifespan`, après les imports existants (ligne ~22) :

```python
import services.agent.tools.<nom>  # noqa: F401
```

3. **Tester** :
```bash
cd backend && pytest tests/test_tool_registry.py -v
```

## Règles
- L'outil peut être sync ou async (`execute_tool` gère les deux)
- Toujours retourner une `str` — l'agent injecte la valeur dans le contexte LLM
- Pas de side-effects persistants sauf si intentionnel et documenté
- Garder la `description` concise : elle est envoyée à Ollama à chaque appel
