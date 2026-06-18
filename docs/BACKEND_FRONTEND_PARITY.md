# Backend ↔ Frontend parity backlog

> **But de ce document.** Le backend expose plusieurs fonctions qui ne sont pas
> (ou pas entièrement) accessibles depuis l'interface React. Ce fichier recense
> **tout ce qui reste à brancher**, classé par priorité, pour servir de backlog à
> la **phase suivante** du projet (une fois le backend stabilisé — fait dans la
> PR de stabilisation). Aucune de ces tâches n'a encore été implémentée côté UI.
>
> Légende des chemins : endpoints backend dans `backend/api/routes/*.py`,
> couche API frontend dans `frontend/src/api/*.ts`, écrans dans
> `frontend/src/pages/*.tsx`.

---

## 1. Essentiel (à brancher en premier)

Ces endpoints existent et fonctionnent côté backend, mais aucune commande UI ne
les appelle. Ce sont des manques fonctionnels visibles pour l'utilisateur.

| Fonction | Endpoint backend | API frontend | Cible UI |
|---|---|---|---|
| Supprimer une session agent | `DELETE /agent/sessions/{id}` | `deleteSession()` *(déjà défini, jamais appelé)* | Bouton corbeille sur chaque ligne de la liste des sessions (`AgentPage.tsx`) |
| Détail d'une session | `GET /agent/sessions/{id}` (renvoie `system_prompt`, `messages`, `tools_used`) | `getSession()` *(défini, jamais appelé)* | Au clic sur une session : recharger l'historique complet au lieu de repartir vide (`AgentPage.tsx`) |
| Supprimer un modèle HF téléchargé | `DELETE /image/hf/models/{id}` | `deleteHFModel()` *(défini, jamais appelé)* | Bouton supprimer dans `HFModelBrowser.tsx` / liste des modèles téléchargés |
| Détail d'un job image | `GET /image/jobs/{id}` | `getJob()` *(défini, jamais appelé)* | Vue détail/agrandissement depuis l'historique (`ImageGenerationPage.tsx`) |
| Upload de dataset | `POST /labs/datasets/upload` (multipart `name`, `task_type`, `files[]`) | **à créer** dans `labs.ts` | Zone d'upload (drag & drop) dans `LabsPage.tsx` |
| Supprimer un dataset | `DELETE /labs/datasets/{id}` | `deleteDataset()` *(défini, jamais appelé)* | Bouton supprimer sur chaque dataset (`LabsPage.tsx`) |
| Exporter un modèle entraîné | `POST /labs/runs/{id}/export` (`format`: onnx/safetensors) | `exportRun()` *(défini, jamais appelé)* | Bouton « Exporter » sur un run terminé (`LabsPage.tsx`) |
| Télécharger l'export | `GET /labs/runs/{id}/export/download` | **à créer** dans `labs.ts` | Lien de téléchargement après export (`LabsPage.tsx`) |

---

## 2. Avancé (options backend non exposées dans l'UI)

Le backend accepte ces paramètres mais l'UI n'offre aucun contrôle ; des valeurs
par défaut sont utilisées silencieusement.

### 2.1 Hyperparamètres d'entraînement — `POST /labs/runs` (`training_config`)
Exposés aujourd'hui : `epochs`, `batch_size`, `learning_rate`.
Consommés par `backend/services/labs/trainer.py` mais **absents de l'UI** :

| Paramètre | Défaut backend | Contrôle UI suggéré |
|---|---|---|
| `weight_decay` | `1e-4` | champ numérique |
| `optimizer` | `adamw` | select : adamw / adam / sgd / rmsprop |
| `lr_scheduler` | `cosine` | select : cosine / linear / onecycle / none |
| `gradient_accumulation_steps` | `1` | champ numérique |
| `gradient_clip_norm` | `1.0` | champ numérique |
| `val_split` | `0.2` | slider 0–0.5 |
| `num_workers` | `2` | champ numérique |
| `use_mixed_precision` | `fp16` | toggle fp16 / no |

> Astuce : `GET /hardware/recommendations` renvoie déjà des suggestions
> (`training.*`) qui peuvent pré-remplir ces champs.

### 2.2 Sélecteur `task_type`
- `POST /labs/datasets/huggingface` : le frontend **code en dur** `"classification"`
  (`LabsPage.tsx`). Exposer un select : classification / detection / segmentation /
  generation / nlp (valeurs de l'enum `Dataset.task_type`).
- `GET /labs/architectures?task_type=&vram_mb=` : le frontend ne passe ni
  `task_type` ni le vrai `vram_mb` (toujours `0`). Brancher le filtrage par tâche
  et passer la VRAM détectée (`useHardwareInfo`) pour ne proposer que des archis
  compatibles.

### 2.3 Pagination (déjà supportée côté backend après stabilisation)
`limit`/`offset` existent sur `GET /image/jobs`, `GET /agent/sessions`,
`GET /labs/datasets`, `GET /labs/runs`. L'UI ne pagine jamais (charge la première
page uniquement). Ajouter un « Charger plus » / pagination sur :
- l'historique d'images (`ImageGenerationPage.tsx`),
- la liste des sessions (`AgentPage.tsx`),
- les datasets et runs (`LabsPage.tsx`).

### 2.4 Streaming token de l'agent
`backend/services/agent/ollama_client.py::stream_chat()` est prêt mais inutilisé ;
le WS agent émet déjà des évènements `token`. Brancher un vrai streaming
token-par-token dans `AgentPage.tsx` (afficher la réponse au fil de l'eau) en
faisant passer `agent.run` par un chemin de streaming.

---

## 3. Notes d'implémentation
- Les helpers de sérialisation backend sont centralisés dans
  `backend/schemas/serializers.py` — toute nouvelle réponse devrait y être ajoutée
  plutôt que recréée inline dans une route.
- Côté frontend, factoriser les nouveaux appels dans `frontend/src/api/*.ts`
  (ne pas appeler axios directement depuis les pages).
- Penser à invalider/rafraîchir les listes après les mutations (delete/upload/export).
