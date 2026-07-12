# Spec — Préparation de données A → Z (labs-app)

**Date** : 2026-07-12
**Statut** : validé par l'utilisateur (design approuvé en session)
**Portée** : labs-app (port 8100) + services partagés `backend/services/labs/`

## Problème

Aujourd'hui, l'import de fichiers dans labs-app copie les fichiers bruts dans un
dossier sans aucune préparation. Le trainer ne sait charger que les datasets
Hugging Face au format arrow (`load_from_disk`) et retombe silencieusement sur
un **dataset factice** pour tout le reste (`trainer.py:77`). Les imports
utilisateur ne servent donc jamais à un vrai entraînement.

## Objectif

L'utilisateur dépose n'importe quoi (dossier, fichiers, zip — images, docs,
texte, tabulaire) et l'app trie, convertit, nettoie et empaquette le tout en un
dataset Hugging Face prêt à entraîner, sélectionnable immédiatement dans un run.
**Le trainer n'est pas modifié** : le format produit correspond exactement à ce
qu'il consomme déjà (colonnes `image`/`text` + `label`, cf. `trainer.py:336-338`).

## Parcours utilisateur (assistant en 2 étapes)

Nouvelle section « Préparer des données » dans labs-app :

1. **Dépôt** — au choix :
   - glisser-déposer de fichiers ou d'un dossier entier (drag & drop +
     sélecteur `webkitdirectory`) → upload vers un dossier de staging ;
   - champ « chemin d'un dossier local » → lecture directe sur disque, aucun
     upload (recommandé pour les gros volumes). Le dossier source n'est
     **jamais modifié** (lecture seule).
   - Les `.zip` déposés sont décompressés dans le staging avant analyse.
2. **Analyse** — `POST /api/data-prep/analyze` renvoie un rapport : type
   détecté, classes trouvées, décompte par format, conversions prévues,
   fichiers ignorés avec raison, doublons, avertissements. Pour un fichier
   tabulaire, le mapping colonnes (texte / label) proposé est affiché et
   corrigeable.
3. **Options + confirmation** — l'utilisateur ajuste : nom du dataset, taille
   d'image cible (32 / 64 / 128 / 224 px, défaut 64), mapping colonnes CSV.
   Clic « Préparer ».
4. **Préparation** — tâche de fond avec progression en direct (polling), puis
   le dataset apparaît dans la liste Datasets, statut « ready », avec
   `num_samples`, `num_classes`, `class_names` renseignés.

## Détection (le « tri »)

Type de chaque fichier détecté par **contenu réel** (signatures/magic bytes,
ouverture Pillow pour les images, tentative de décodage pour le texte),
l'extension ne servant que de repli. Un `.jpg` renommé `.txt` est traité comme
une image.

Règles de structure (à la racine du dépôt analysé) :

| Structure trouvée | Interprétation |
|---|---|
| ≥ 2 sous-dossiers contenant chacun ≥ 1 fichier supporté | 1 sous-dossier = 1 classe → **classification** (images ou textes selon le contenu majoritaire) |
| Images en vrac (sans sous-dossiers) | Avertissement « sans étiquettes » dans le rapport + conseil de ranger en sous-dossiers ; non empaquetable en classification |
| Textes en vrac (txt, docx, pdf, html, md, rtf) | **Corpus NLP** : colonne `text` seule (1 ligne = 1 document), utilisable pour l'entraînement de tokenizers |
| Un fichier tabulaire (csv, tsv, json, jsonl) | **Classification de texte** : détection colonne texte (colonne string la plus longue en moyenne) + colonne label (faible cardinalité), confirmée par l'utilisateur |
| Contenu mixte | Le type majoritaire gagne ; le reste est listé « ignoré » dans le rapport |

## Conversions et nettoyage

**Documents → texte** : pdf (`pypdf`), docx (`python-docx`), rtf (`striprtf`),
html (parseur stdlib `html.parser`), md (texte quasi brut, balises légères
retirées). Nouvelles dépendances : `pypdf`, `python-docx`, `striprtf`
(pures Python, ajoutées à `backend/requirements.txt`).

**Images → JPEG normalisé** : webp, bmp, tiff, gif, png, jpeg… via Pillow
(déjà installé) : conversion RGB, redimensionnement carré à la taille cible
(redimensionnement du petit côté + crop centré), sauvegarde JPEG qualité 95.
Images corrompues (échec `Image.open`/`verify`) écartées et listées.

**Nettoyage texte** : encodage détecté et réparé (`charset-normalizer`, déjà
présent via requests — ajouté explicitement aux requirements), normalisation
Unicode NFC, caractères de contrôle retirés (sauf `\n` et `\t`), espaces de fin
de ligne supprimés, plus de 2 lignes vides consécutives réduites, textes vides
après nettoyage écartés.

**Dédoublonnage** : hash sha256 — sur les octets bruts pour les images, sur le
texte nettoyé pour les documents. Les doublons sont écartés et comptés dans le
rapport.

## Empaquetage (format de sortie)

Dataset Hugging Face sauvé via `save_to_disk` dans
`settings.datasets_dir/<dataset_id>`, sous forme de `DatasetDict` avec un seul
split `train` (le trainer fait déjà lui-même le split train/val) :

- **Classification d'images** : colonnes `image` (feature `datasets.Image`) +
  `label` (`ClassLabel` avec `names` = noms des sous-dossiers, ordre trié).
- **Classification de texte** (dossiers ou tabulaire) : `text` (string) +
  `label` (`ClassLabel`).
- **Corpus NLP** : `text` seul. `task_type` = « nlp ». (Non entraînable en
  classification — le rapport le dit clairement — mais consommable par le
  module tokenizers.)

Enregistrement en base : modèle `Dataset` existant, **aucune migration** —
`source="upload"`, `source_identifier` = chemin/nom d'origine, `task_type`,
`num_samples`, `num_classes`, `class_names`, `size_bytes`, `status`
(`downloading` → `ready` / `error`).

## Architecture technique

```
backend/services/labs/data_prep/
  __init__.py
  scanner.py      parcours récursif, sniffing de type, détection structure/classes
                  → AnalysisReport (dataclass sérialisable JSON)
  converters.py   extract_text(path) → str · normalize_image(path, size) → JPEG bytes
  cleaner.py      clean_text(str) → str · dédoublonnage (hashes)
  packager.py     build + save_to_disk du dataset HF (image|text + label)
  pipeline.py     analyze(source_dir) · prepare(prep_id, options, db_session)
                  orchestration, progression, gestion d'erreurs
```

Routes ajoutées dans `labs-app/main.py` (mêmes conventions que les routes
existantes, sessions via `AsyncSessionLocal()` pour les tâches de fond) :

- `POST /api/data-prep/upload` — multipart ; les chemins relatifs
  (`webkitRelativePath`) sont préservés **après sanitisation par composant**
  (chaque segment passé par `Path(...).name`, segments `..` rejetés) pour
  conserver les sous-dossiers de classes ; zip décompressés avec protection
  zip-slip (entrée résolue hors de la cible → rejetée). Retourne `prep_id`.
- `POST /api/data-prep/analyze` — body : `prep_id` (staging) **ou**
  `local_path` (doit exister et être un dossier). Retourne le rapport.
- `POST /api/data-prep/prepare` — body : source + options (nom, taille image,
  mapping colonnes). Crée l'enregistrement `Dataset` (status `downloading`),
  lance la pipeline en tâche de fond, retourne `dataset_id`.
- `GET /api/data-prep/progress/{prep_id}` — `{stage, done, total, message}`
  depuis un dict en mémoire (app locale mono-utilisateur, pas de persistance
  nécessaire ; une entrée est purgée à la fin du run).

Staging : `data/staging/<prep_id>/`, purgé après préparation réussie et au
démarrage de l'app (staging orphelin).

UI (`labs-app/static/`) : nouvelle entrée de navigation « Préparer », dropzone
+ champ chemin, écran rapport (cartes de synthèse + liste des fichiers ignorés
avec raisons), options, barre de progression (polling 1 s), lien vers la liste
Datasets à la fin. Vanilla HTML/CSS/JS comme le reste, styles cohérents avec
`style.css` existant.

## Gestion d'erreurs

- **Par fichier** : toute erreur (corrompu, illisible, conversion échouée)
  écarte le fichier, l'ajoute au rapport avec la raison, et la préparation
  continue. Un dépôt ne peut jamais échouer à cause d'un seul fichier.
- **Globale** (chemin introuvable, zéro fichier exploitable, disque plein,
  exception inattendue) : enregistrement `Dataset` passé en `error` avec
  `error_message` lisible, affiché dans l'UI.
- Si l'analyse ne trouve **aucun** fichier exploitable, le bouton « Préparer »
  est désactivé et le rapport explique pourquoi.

## Tests (`backend/tests/test_labs_data_prep.py`)

Mêmes conventions que `test_labs_tokenizers.py` :

- **scanner** : dossier-par-classe images, dossier-par-classe textes, vrac,
  tabulaire, mixte, extension mensongère (jpg renommé txt).
- **converters** : fixtures générées dans le test (docx via python-docx, pdf
  via pypdf, images via Pillow) ; fichier corrompu → écarté proprement.
- **cleaner** : encodage, normalisation, dédoublonnage.
- **packager + round-trip** : dépôt fixture → `prepare` → `load_from_disk` →
  colonnes/features exactement conformes à ce que `_tensor_dataset_from_hf`
  attend (dont vérification que toutes les images ont la même taille).
- **routes** : upload avec sous-dossiers, analyze local_path, prepare + statut
  final `ready`, cas d'erreur (chemin inexistant).

## Hors périmètre (explicitement)

Vidéos (extraction de frames), audio, interface d'étiquetage manuel,
augmentation de données, splits multiples, tâches détection/segmentation,
intégration dans l'app principale (l'app principale pourra réutiliser le
service plus tard, rien ne l'empêche).
