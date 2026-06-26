# Lancer les tests

Exécute les tests appropriés selon le contexte. Arguments optionnels : `$ARGUMENTS` (ex: `heavy`, `unit`, `frontend`, ou un nom de fichier/test).

## Commandes selon le contexte

### Tests backend rapides (pas de GPU, par défaut en CI)
```bash
cd backend && pytest -x -q
```

### Tests d'un fichier spécifique
```bash
cd backend && pytest tests/<fichier>.py -v
```

### Tests d'une fonction spécifique
```bash
cd backend && pytest tests/<fichier>.py::test_<nom> -v
```

### Tests lents / GPU (marqueur `heavy`)
```bash
cd backend && pytest -m heavy -v
```

### Vérification types + build frontend
```bash
cd frontend && npm run build
```

### Lint backend
```bash
cd backend && ruff check .
cd backend && ruff check . --fix  # auto-correction
```

## Fichiers de tests existants

| Fichier | Couvre |
|---|---|
| `test_calculator.py` | outil calculatrice (AST eval) |
| `test_tool_registry.py` | enregistrement + exécution outils |
| `test_planner.py` | boucle ReAct de l'agent |
| `test_model_registry.py` | registre modèles image |
| `test_recommender.py` | recommandations hardware |
| `test_trainer_dataset.py` | Labs trainer + dataset manager |
| `test_api_integration.py` | routes REST (httpx async) |
| `test_code_executor.py` | sandbox exécution Python |
| `test_hf_and_security.py` | connecteur HF + auth token |
| `test_e2e_heavy.py` | e2e complet (marqué `heavy`) |

## Couverture
```bash
cd backend && pytest --cov=. --cov-report=term-missing -q
```

## Règles
- Toujours lancer `-x` (stop au premier échec) lors d'un débogage
- Les tests heavy nécessitent torch + un GPU ou beaucoup de RAM
- `conftest.py` fournit `async_client`, `db_session` (SQLite en mémoire)
- Nouveaux tests : ajouter dans `backend/tests/test_<module>.py`
