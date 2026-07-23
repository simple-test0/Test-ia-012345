# Préparation de données A → Z (labs-app) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'utilisateur dépose n'importe quoi (dossier, fichiers, zip — images, docs, texte, tabulaire) dans labs-app ; l'app trie, convertit, nettoie et empaquette le tout en dataset Hugging Face prêt à entraîner.

**Architecture:** Nouveau package `backend/services/labs/data_prep/` en 5 modules (cleaner, converters, scanner, packager, pipeline) + 4 endpoints ajoutés au router labs existant (déjà inclus par labs-app ET l'app principale — aucun câblage nouveau) + une vue « Préparer » dans l'UI vanilla de labs-app. Le format de sortie (`DatasetDict{"train"}` avec colonnes `image|text` + `label`) est exactement celui que `trainer.py:_tensor_dataset_from_hf` consomme déjà — **le trainer n'est pas modifié**.

**Tech Stack:** FastAPI, SQLAlchemy async, HF `datasets` 3.0.1 (installé), Pillow 10.4 (installé), pypdf / python-docx / striprtf / charset-normalizer (à ajouter), HTML/CSS/JS vanilla.

**Spec:** `docs/superpowers/specs/2026-07-12-labs-data-prep-design.md`

## Global Constraints

- Tout est async côté routes ; le travail bloquant passe par `run_in_executor` (pattern de `dataset_manager.py`).
- ruff I001 : ligne vide entre imports third-party et imports locaux, **même à l'intérieur des fonctions**.
- Routes : `Depends(get_db)` ; tâches de fond : `AsyncSessionLocal()` passé en paramètre `db_session`.
- Erreurs HTTP : `raise HTTPException(status_code=..., detail="...")`, detail en français (copie UI existante).
- Pas de commentaires sauf si le POURQUOI est non évident.
- Aucun changement de schéma DB : on réutilise le modèle `Dataset` tel quel (`source="upload"`).
- Le préfixe `/api/v1` est appliqué par les apps — les routes du router sont écrites sans lui.
- Tests : `cd backend && python -m pytest tests/test_labs_data_prep.py -v` ; garde `pytestmark = pytest.mark.skipif(not _HAS_TORCH, ...)` comme les fichiers de test existants (l'import de `main` tire torch).
- Commits fréquents, messages style repo (`feat(labs): …`), un commit par tâche minimum.

---

### Task 1: Dépendances + nettoyeur de texte (`cleaner.py`)

**Files:**
- Modify: `backend/requirements.txt` (ajout en fin de fichier)
- Create: `backend/services/labs/data_prep/__init__.py` (vide)
- Create: `backend/services/labs/data_prep/cleaner.py`
- Create: `backend/tests/test_labs_data_prep.py`

**Interfaces:**
- Consumes: rien.
- Produces: `decode_bytes(data: bytes) -> str` · `clean_text(raw: str) -> str` · `content_hash(data: bytes | str) -> str` (hex sha256). Les tâches 2, 3 et 5 importent ces trois fonctions depuis `services.labs.data_prep.cleaner`.

- [ ] **Step 1: Ajouter les dépendances**

Ajouter à la fin de `backend/requirements.txt` :

```
# Préparation de données (labs data prep)
pypdf==5.1.0
python-docx==1.1.2
striprtf==0.0.26
charset-normalizer==3.4.0
```

Puis installer :

```bash
cd backend && .venv/Scripts/python -m pip install pypdf==5.1.0 python-docx==1.1.2 striprtf==0.0.26 charset-normalizer==3.4.0
```

Expected: `Successfully installed ...` (charset-normalizer peut déjà être présent via requests — pas grave).

- [ ] **Step 2: Écrire les tests qui échouent**

Créer `backend/tests/test_labs_data_prep.py` :

```python
"""Tests du pipeline de préparation de données (scan, conversion, nettoyage, empaquetage, routes)."""
import importlib.util
import io
import time

import pytest

_HAS_TORCH = importlib.util.find_spec("torch") is not None
pytestmark = pytest.mark.skipif(not _HAS_TORCH, reason="torch not installed")


# ── Cleaner ───────────────────────────────────────────────────────────────────


def test_clean_text_normalizes_whitespace_and_controls():
    from services.labs.data_prep.cleaner import clean_text

    raw = "ligne un   \r\nligne deux\r\n\n\n\n\nligne trois\x00\x08"
    assert clean_text(raw) == "ligne un\nligne deux\n\nligne trois"


def test_clean_text_composes_unicode_and_keeps_tabs():
    from services.labs.data_prep.cleaner import clean_text

    assert clean_text("café") == "café"
    assert clean_text("a\tb") == "a\tb"


def test_clean_text_empty_input():
    from services.labs.data_prep.cleaner import clean_text

    assert clean_text("") == ""
    assert clean_text("\n\n\n") == ""


def test_decode_bytes_utf8_and_latin1():
    from services.labs.data_prep.cleaner import decode_bytes

    assert decode_bytes("héllo".encode("utf-8")) == "héllo"
    phrase = "Le café est très chaud, écoute la météo du sud de la Méditerranée"
    assert "café" in decode_bytes(phrase.encode("latin-1"))


def test_content_hash_str_and_bytes_agree():
    from services.labs.data_prep.cleaner import content_hash

    assert content_hash("abc") == content_hash(b"abc")
    assert content_hash("abc") != content_hash("abd")
```

- [ ] **Step 3: Vérifier l'échec**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v
```

Expected: 5 FAILED avec `ModuleNotFoundError: No module named 'services.labs.data_prep'`.

- [ ] **Step 4: Implémenter**

Créer `backend/services/labs/data_prep/__init__.py` (fichier vide), puis `backend/services/labs/data_prep/cleaner.py` :

```python
import hashlib
import re
import unicodedata

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def decode_bytes(data: bytes) -> str:
    """Décode des octets en réparant les encodages inconnus (jamais d'exception)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best)
        return data.decode("latin-1", errors="replace")


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_CHARS.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def content_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
```

- [ ] **Step 5: Vérifier le passage**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v
```

Expected: 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/services/labs/data_prep/__init__.py backend/services/labs/data_prep/cleaner.py backend/tests/test_labs_data_prep.py
git commit -m "feat(labs): data-prep — nettoyage de texte, décodage, hachage + dépendances"
```

---

### Task 2: Convertisseurs documents → texte et images → JPEG (`converters.py`)

**Files:**
- Create: `backend/services/labs/data_prep/converters.py`
- Test: `backend/tests/test_labs_data_prep.py` (ajout de sections)

**Interfaces:**
- Consumes: `decode_bytes` de la tâche 1.
- Produces: `class ConversionError(Exception)` · `extract_text(path: Path, kind: str) -> str` où `kind ∈ {"txt","md","html","rtf","docx","pdf"}` · `normalize_image(path: Path, size: int) -> PIL.Image.Image` (RGB, carré size×size). La tâche 5 importe les trois.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `backend/tests/test_labs_data_prep.py` :

```python
# ── Converters ────────────────────────────────────────────────────────────────


def test_extract_text_txt_and_md(tmp_path):
    from services.labs.data_prep.converters import extract_text

    p = tmp_path / "a.txt"
    p.write_text("bonjour texte", encoding="utf-8")
    assert extract_text(p, "txt") == "bonjour texte"
    m = tmp_path / "b.md"
    m.write_text("# Titre\ncorps markdown", encoding="utf-8")
    assert "corps markdown" in extract_text(m, "md")


def test_extract_text_html_skips_scripts(tmp_path):
    from services.labs.data_prep.converters import extract_text

    p = tmp_path / "page.html"
    p.write_text(
        "<html><head><script>var x=1;</script><style>b{}</style></head>"
        "<body><h1>Un titre</h1><p>Du contenu utile.</p></body></html>",
        encoding="utf-8",
    )
    out = extract_text(p, "html")
    assert "Du contenu utile." in out
    assert "var x" not in out


def test_extract_text_rtf(tmp_path):
    from services.labs.data_prep.converters import extract_text

    p = tmp_path / "doc.rtf"
    p.write_text(r"{\rtf1\ansi Bonjour RTF}", encoding="ascii")
    assert "Bonjour RTF" in extract_text(p, "rtf")


def test_extract_text_docx(tmp_path):
    import docx

    from services.labs.data_prep.converters import extract_text

    p = tmp_path / "doc.docx"
    d = docx.Document()
    d.add_paragraph("Premier paragraphe docx")
    d.add_paragraph("Second paragraphe")
    d.save(str(p))
    out = extract_text(p, "docx")
    assert "Premier paragraphe docx" in out and "Second paragraphe" in out


def test_extract_text_pdf_blank_and_corrupt(tmp_path):
    from pypdf import PdfWriter

    from services.labs.data_prep.converters import ConversionError, extract_text

    p = tmp_path / "blank.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with p.open("wb") as fh:
        w.write(fh)
    assert extract_text(p, "pdf") == ""

    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 pas un vrai pdf")
    with pytest.raises(ConversionError):
        extract_text(bad, "pdf")


def test_normalize_image_resizes_to_rgb_square(tmp_path):
    from PIL import Image

    from services.labs.data_prep.converters import normalize_image

    p = tmp_path / "img.png"
    Image.new("RGBA", (10, 30), (255, 0, 0, 255)).save(p)
    out = normalize_image(p, 64)
    assert out.size == (64, 64)
    assert out.mode == "RGB"


def test_normalize_image_rejects_non_image(tmp_path):
    from services.labs.data_prep.converters import ConversionError, normalize_image

    p = tmp_path / "notimg.jpg"
    p.write_text("ceci n'est pas une image", encoding="utf-8")
    with pytest.raises(ConversionError):
        normalize_image(p, 64)
```

- [ ] **Step 2: Vérifier l'échec**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v -k "extract_text or normalize_image"
```

Expected: 7 FAILED avec `ModuleNotFoundError` / `ImportError` sur `converters`.

- [ ] **Step 3: Implémenter**

Créer `backend/services/labs/data_prep/converters.py` :

```python
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image, ImageOps

from services.labs.data_prep.cleaner import decode_bytes


class ConversionError(Exception):
    """Fichier inconvertible ; le message est montré tel quel à l'utilisateur."""


class _HtmlText(HTMLParser):
    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.chunks.append(data.strip())


def extract_text(path: Path, kind: str) -> str:
    try:
        if kind in ("txt", "md"):
            return decode_bytes(path.read_bytes())
        if kind == "html":
            parser = _HtmlText()
            parser.feed(decode_bytes(path.read_bytes()))
            return "\n".join(parser.chunks)
        if kind == "rtf":
            from striprtf.striprtf import rtf_to_text

            return rtf_to_text(decode_bytes(path.read_bytes()))
        if kind == "docx":
            import docx

            document = docx.Document(str(path))
            return "\n".join(p.text for p in document.paragraphs)
        if kind == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ConversionError(f"conversion {kind} impossible: {exc}") from exc
    raise ConversionError(f"type non convertible en texte: {kind}")


def normalize_image(path: Path, size: int) -> Image.Image:
    try:
        with Image.open(path) as im:
            im.load()
            rgb = im.convert("RGB")
    except Exception as exc:
        raise ConversionError(f"image illisible: {exc}") from exc
    return ImageOps.fit(rgb, (size, size), Image.Resampling.LANCZOS)
```

- [ ] **Step 4: Vérifier le passage**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v
```

Expected: 12 PASSED (5 de la tâche 1 + 7 nouveaux).

- [ ] **Step 5: Commit**

```bash
git add backend/services/labs/data_prep/converters.py backend/tests/test_labs_data_prep.py
git commit -m "feat(labs): data-prep — conversion docs→txt (pdf, docx, rtf, html, md) et images→jpeg normalisé"
```

---

### Task 3: Scanner — sniffing, structure, rapport d'analyse (`scanner.py`)

**Files:**
- Create: `backend/services/labs/data_prep/scanner.py`
- Test: `backend/tests/test_labs_data_prep.py` (ajout)

**Interfaces:**
- Consumes: `decode_bytes` (tâche 1).
- Produces (importés par la tâche 5) :
  - `TEXT_KINDS: set[str]` = `{"txt","md","html","rtf","docx","pdf"}`
  - `sniff_file(path: Path) -> str` — retourne `"image" | "txt" | "md" | "html" | "rtf" | "docx" | "pdf" | "tabular" | "zip" | "unknown"`
  - `@dataclass UsableFile(path: Path, kind: str, label: str | None)`
  - `@dataclass AnalysisReport(kind, source_dir, classes, counts, conversions, num_files, num_usable, ignored, warnings, tabular)` avec `to_dict() -> dict` ; `kind ∈ {"image_classification","text_classification","text_corpus","tabular","unlabeled_images","empty"}`
  - `scan_full(source_dir: Path) -> tuple[AnalysisReport, list[UsableFile]]` et `scan(source_dir: Path) -> AnalysisReport`
  - `read_tabular(path: Path, max_rows: int = 0) -> tuple[list[str], list[dict]]` · `inspect_tabular(path: Path, max_rows: int = 1000) -> dict` (clés : `file, columns, num_rows, suggested_text_column, suggested_label_column`)

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `backend/tests/test_labs_data_prep.py` :

```python
# ── Scanner ───────────────────────────────────────────────────────────────────


def _make_image(path, size=(20, 20), color=(255, 0, 0), fmt=None):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format=fmt)


def test_sniff_file_detects_real_content(tmp_path):
    from services.labs.data_prep.scanner import sniff_file

    disguised = tmp_path / "photo.txt"
    _make_image(disguised, fmt="PNG")
    assert sniff_file(disguised) == "image"

    txt = tmp_path / "notes.log"
    txt.write_text("du texte libre", encoding="utf-8")
    assert sniff_file(txt) == "txt"

    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"%PDF-1.4 ...")
    assert sniff_file(pdf) == "pdf"

    csvf = tmp_path / "t.csv"
    csvf.write_text("a,b\n1,2\n", encoding="utf-8")
    assert sniff_file(csvf) == "tabular"

    binary = tmp_path / "prog.bin"
    binary.write_bytes(b"\x00\x01\x02\x03" * 10)
    assert sniff_file(binary) == "unknown"


def test_scan_image_classification(tmp_path):
    from services.labs.data_prep.scanner import scan_full

    for i in range(3):
        _make_image(tmp_path / "chats" / f"c{i}.png")
        _make_image(tmp_path / "chiens" / f"d{i}.png")
    (tmp_path / "chats" / "notes.txt").write_text("intrus texte", encoding="utf-8")

    report, usable = scan_full(tmp_path)
    assert report.kind == "image_classification"
    assert report.classes == ["chats", "chiens"]
    assert report.num_usable == 6
    assert len(usable) == 6
    assert {u.label for u in usable} == {"chats", "chiens"}
    assert any("minoritaire" in i["reason"] for i in report.ignored)


def test_scan_text_classification_and_corpus(tmp_path):
    from services.labs.data_prep.scanner import scan_full

    pos, neg = tmp_path / "cls" / "positif", tmp_path / "cls" / "negatif"
    pos.mkdir(parents=True)
    neg.mkdir(parents=True)
    (pos / "a.txt").write_text("super produit", encoding="utf-8")
    (neg / "b.txt").write_text("très déçu", encoding="utf-8")
    report, usable = scan_full(tmp_path / "cls")
    assert report.kind == "text_classification"
    assert report.classes == ["negatif", "positif"]

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "un.txt").write_text("document un", encoding="utf-8")
    (corpus / "deux.txt").write_text("document deux", encoding="utf-8")
    report, usable = scan_full(corpus)
    assert report.kind == "text_corpus"
    assert report.num_usable == 2
    assert all(u.label is None for u in usable)


def test_scan_unwraps_single_root_folder(tmp_path):
    from services.labs.data_prep.scanner import scan_full

    for i in range(2):
        _make_image(tmp_path / "depot" / "animaux" / "chats" / f"c{i}.png")
        _make_image(tmp_path / "depot" / "animaux" / "chiens" / f"d{i}.png")
    report, _ = scan_full(tmp_path / "depot")
    assert report.kind == "image_classification"
    assert report.classes == ["chats", "chiens"]


def test_scan_unlabeled_images_and_empty(tmp_path):
    from services.labs.data_prep.scanner import scan_full

    vrac = tmp_path / "vrac"
    vrac.mkdir()
    _make_image(vrac / "a.png")
    _make_image(vrac / "b.png")
    report, usable = scan_full(vrac)
    assert report.kind == "unlabeled_images"
    assert report.num_usable == 0
    assert report.warnings

    vide = tmp_path / "vide"
    vide.mkdir()
    report, _ = scan_full(vide)
    assert report.kind == "empty"


def test_scan_tabular_and_inspect(tmp_path):
    from services.labs.data_prep.scanner import inspect_tabular, scan_full

    csvf = tmp_path / "avis.csv"
    rows = ["texte,sentiment"]
    for i in range(20):
        rows.append(f"un avis client numéro {i} plutôt détaillé,{'pos' if i % 2 else 'neg'}")
    csvf.write_text("\n".join(rows), encoding="utf-8")

    report, usable = scan_full(tmp_path)
    assert report.kind == "tabular"
    assert report.tabular["suggested_text_column"] == "texte"
    assert report.tabular["suggested_label_column"] == "sentiment"

    info = inspect_tabular(csvf)
    assert info["num_rows"] == 20
    assert info["columns"] == ["texte", "sentiment"]


def test_read_tabular_jsonl(tmp_path):
    from services.labs.data_prep.scanner import read_tabular

    p = tmp_path / "d.jsonl"
    p.write_text('{"text": "un", "label": "a"}\n{"text": "deux", "label": "b"}\n', encoding="utf-8")
    columns, rows = read_tabular(p)
    assert columns == ["text", "label"]
    assert len(rows) == 2 and rows[1]["text"] == "deux"


def test_report_to_dict_is_json_safe(tmp_path):
    import json

    from services.labs.data_prep.scanner import scan

    (tmp_path / "a.txt").write_text("texte", encoding="utf-8")
    report = scan(tmp_path)
    json.dumps(report.to_dict())
```

- [ ] **Step 2: Vérifier l'échec**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v -k "sniff or scan or tabular or to_dict"
```

Expected: 8 FAILED (`ModuleNotFoundError` sur `scanner`).

- [ ] **Step 3: Implémenter**

Créer `backend/services/labs/data_prep/scanner.py` :

```python
import csv
import io
import json
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image

from services.labs.data_prep.cleaner import decode_bytes

TEXT_KINDS = {"txt", "md", "html", "rtf", "docx", "pdf"}
TABULAR_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl"}
IGNORED_DIRS = {"__pycache__", ".git", "node_modules"}


@dataclass
class UsableFile:
    path: Path
    kind: str
    label: str | None


@dataclass
class AnalysisReport:
    kind: str
    source_dir: str
    classes: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    conversions: dict = field(default_factory=dict)
    num_files: int = 0
    num_usable: int = 0
    ignored: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    tabular: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def sniff_file(path: Path) -> str:
    """Détecte le type par le contenu réel ; l'extension n'est qu'un repli."""
    try:
        with path.open("rb") as fh:
            head = fh.read(4096)
    except OSError:
        return "unknown"
    if not head:
        return "unknown"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
        except Exception:
            return "unknown"
        return "docx" if "word/document.xml" in names else "zip"
    try:
        with Image.open(path) as im:
            im.verify()
        return "image"
    except Exception:
        pass
    text = decode_bytes(head)
    if "\x00" in text:
        return "unknown"
    suffix = path.suffix.lower()
    if suffix in TABULAR_SUFFIXES:
        return "tabular"
    lowered = text.lstrip().lower()
    if suffix in (".html", ".htm") or lowered.startswith(("<!doctype html", "<html")):
        return "html"
    if suffix == ".md":
        return "md"
    return "txt"


def _unwrap_root(source_dir: Path) -> Path:
    """Descend dans les dossiers d'emballage uniques (dépôt d'un seul dossier, zip)."""
    current = source_dir
    for _ in range(8):
        try:
            children = [c for c in current.iterdir() if not c.name.startswith(".")]
        except OSError:
            break
        dirs = [c for c in children if c.is_dir() and c.name not in IGNORED_DIRS]
        files = [c for c in children if c.is_file()]
        if len(dirs) == 1 and not files:
            current = dirs[0]
        else:
            break
    return current


def scan(source_dir: Path) -> AnalysisReport:
    return scan_full(source_dir)[0]


def scan_full(source_dir: Path) -> tuple[AnalysisReport, list[UsableFile]]:
    root = _unwrap_root(Path(source_dir))
    report = AnalysisReport(kind="empty", source_dir=str(source_dir))
    entries: list[tuple[Path, str, str | None]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") or part in IGNORED_DIRS for part in rel.parts):
            continue
        report.num_files += 1
        kind = sniff_file(path)
        if kind in ("unknown", "zip"):
            reason = "archive non décompressée" if kind == "zip" else "type de fichier non reconnu"
            report.ignored.append({"path": str(rel), "reason": reason})
            continue
        top = rel.parts[0] if len(rel.parts) > 1 else None
        entries.append((path, kind, top))
        report.counts[kind] = report.counts.get(kind, 0) + 1

    class_files: dict[str, list] = {}
    for path, kind, top in entries:
        if top is not None and kind != "tabular":
            class_files.setdefault(top, []).append(kind)

    if len(class_files) >= 2:
        return report, _finish_classification(report, entries, class_files, root)
    return report, _finish_flat(report, entries, root)


def _finish_classification(report, entries, class_files, root) -> list[UsableFile]:
    n_images = sum(1 for kinds in class_files.values() for k in kinds if k == "image")
    n_texts = sum(1 for kinds in class_files.values() for k in kinds if k in TEXT_KINDS)
    majority_image = n_images >= n_texts
    report.kind = "image_classification" if majority_image else "text_classification"
    report.classes = sorted(class_files)

    usable: list[UsableFile] = []
    for path, kind, top in entries:
        rel = str(path.relative_to(root))
        if top is None or top not in class_files:
            report.ignored.append({"path": rel, "reason": "hors des dossiers de classes"})
        elif majority_image != (kind == "image"):
            report.ignored.append({"path": rel, "reason": "type minoritaire dans ce dépôt"})
        else:
            usable.append(UsableFile(path=path, kind=kind, label=top))
    report.num_usable = len(usable)
    _plan_conversions(report, usable)
    return usable


def _finish_flat(report, entries, root) -> list[UsableFile]:
    images = [(p, k) for p, k, _ in entries if k == "image"]
    texts = [(p, k) for p, k, _ in entries if k in TEXT_KINDS]
    tabulars = [(p, k) for p, k, _ in entries if k == "tabular"]

    def _ignore(items, reason):
        for p, _ in items:
            report.ignored.append({"path": str(p.relative_to(root)), "reason": reason})

    if tabulars and len(tabulars) >= max(len(images), len(texts)):
        report.kind = "tabular"
        report.tabular = inspect_tabular(tabulars[0][0])
        report.num_usable = 1
        _ignore(tabulars[1:], "un seul fichier tabulaire est traité à la fois")
        _ignore(images + texts, "type minoritaire dans ce dépôt")
        if report.tabular["suggested_label_column"] is None:
            report.warnings.append(
                "Aucune colonne d'étiquettes détectée — corrigez le mapping si besoin."
            )
        return [UsableFile(path=tabulars[0][0], kind="tabular", label=None)]

    if images and len(images) >= len(texts):
        report.kind = "unlabeled_images"
        report.warnings.append(
            "Images sans étiquettes : rangez-les dans des sous-dossiers (un par classe) "
            "pour la classification."
        )
        _ignore(texts + tabulars, "type minoritaire dans ce dépôt")
        return []

    if texts:
        report.kind = "text_corpus"
        usable = [UsableFile(path=p, kind=k, label=None) for p, k in texts]
        report.num_usable = len(usable)
        _ignore(images + tabulars, "type minoritaire dans ce dépôt")
        _plan_conversions(report, usable)
        return usable

    return []


def _plan_conversions(report: AnalysisReport, usable: list[UsableFile]) -> None:
    for uf in usable:
        if uf.kind in TEXT_KINDS and uf.kind != "txt":
            key = f"{uf.kind} → txt"
        elif uf.kind == "image" and uf.path.suffix.lower() not in (".jpg", ".jpeg"):
            key = "image → jpeg"
        else:
            continue
        report.conversions[key] = report.conversions.get(key, 0) + 1


def read_tabular(path: Path, max_rows: int = 0) -> tuple[list, list]:
    raw = decode_bytes(path.read_bytes())
    suffix = path.suffix.lower()
    rows: list[dict] = []
    if suffix == ".jsonl" or (suffix == ".json" and raw.lstrip()[:1] == "{"):
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            if max_rows and len(rows) >= max_rows:
                break
    elif suffix == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)][: max_rows or None]
    else:
        delimiter = "\t" if suffix == ".tsv" else ","
        for row in csv.DictReader(io.StringIO(raw), delimiter=delimiter):
            rows.append({k: (v or "") for k, v in row.items() if k is not None})
            if max_rows and len(rows) >= max_rows:
                break
    columns = list(rows[0].keys()) if rows else []
    return columns, rows


def inspect_tabular(path: Path, max_rows: int = 1000) -> dict:
    columns, rows = read_tabular(path, max_rows)
    info = {
        "file": path.name,
        "columns": columns,
        "num_rows": len(rows),
        "suggested_text_column": None,
        "suggested_label_column": None,
    }
    if not rows or not columns:
        return info
    avg_len = {}
    distinct = {}
    for col in columns:
        values = [str(r.get(col, "")) for r in rows]
        avg_len[col] = sum(len(v) for v in values) / len(values)
        distinct[col] = len(set(values))
    text_col = max(columns, key=lambda c: avg_len[c])
    info["suggested_text_column"] = text_col
    label_limit = max(2, int(len(rows) * 0.2))
    candidates = [c for c in columns if c != text_col and 2 <= distinct[c] <= label_limit]
    if candidates:
        info["suggested_label_column"] = min(candidates, key=lambda c: distinct[c])
    return info
```

- [ ] **Step 4: Vérifier le passage**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v
```

Expected: 20 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/labs/data_prep/scanner.py backend/tests/test_labs_data_prep.py
git commit -m "feat(labs): data-prep — scanner (sniffing par contenu, classes, tabulaire, rapport)"
```

---

### Task 4: Empaquetage au format dataset Hugging Face (`packager.py`)

**Files:**
- Create: `backend/services/labs/data_prep/packager.py`
- Test: `backend/tests/test_labs_data_prep.py` (ajout)

**Interfaces:**
- Consumes: rien (la lib `datasets` seulement).
- Produces (importés par la tâche 5) :
  - `package_image_classification(images: list[dict], labels: list[int], class_names: list[str], out_dir: Path) -> int` — chaque élément de `images` est `{"bytes": <jpeg bytes>, "path": "<nom>.jpg"}` (les octets sont **embarqués** dans l'arrow : aucune dépendance à des fichiers sur disque).
  - `package_texts(texts: list[str], labels: list[int] | None = None, class_names: list[str] | None = None, *, out_dir: Path) -> int`
  - Les deux sauvegardent un `DatasetDict({"train": ...})` via `save_to_disk(str(out_dir))` et retournent le nombre d'exemples.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `backend/tests/test_labs_data_prep.py` :

```python
# ── Packager ──────────────────────────────────────────────────────────────────


def _jpeg_bytes(color, size=32):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, "JPEG")
    return buf.getvalue()


def test_package_images_roundtrip_matches_trainer_expectations(tmp_path):
    from datasets import load_from_disk

    from services.labs.data_prep.packager import package_image_classification

    images = [
        {"bytes": _jpeg_bytes((255, 0, 0)), "path": "0.jpg"},
        {"bytes": _jpeg_bytes((0, 255, 0)), "path": "1.jpg"},
        {"bytes": _jpeg_bytes((0, 0, 255)), "path": "2.jpg"},
    ]
    n = package_image_classification(images, [0, 1, 0], ["chats", "chiens"], tmp_path / "out")
    assert n == 3

    loaded = load_from_disk(str(tmp_path / "out"))
    split = loaded["train"]
    assert set(split.column_names) == {"image", "label"}
    assert split.features["label"].names == ["chats", "chiens"]
    first = split[0]["image"]
    assert first.size == (32, 32)
    sizes = {im.size for im in split["image"]}
    assert sizes == {(32, 32)}


def test_package_texts_with_and_without_labels(tmp_path):
    from datasets import load_from_disk

    from services.labs.data_prep.packager import package_texts

    n = package_texts(
        ["très bon", "nul", "excellent"],
        labels=[1, 0, 1],
        class_names=["neg", "pos"],
        out_dir=tmp_path / "cls",
    )
    assert n == 3
    split = load_from_disk(str(tmp_path / "cls"))["train"]
    assert set(split.column_names) == {"text", "label"}
    assert split.features["label"].names == ["neg", "pos"]
    assert split[0]["text"] == "très bon"

    n = package_texts(["doc un", "doc deux"], out_dir=tmp_path / "corpus")
    assert n == 2
    split = load_from_disk(str(tmp_path / "corpus"))["train"]
    assert split.column_names == ["text"]
```

- [ ] **Step 2: Vérifier l'échec**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v -k "package"
```

Expected: 2 FAILED (`ModuleNotFoundError` sur `packager`).

- [ ] **Step 3: Implémenter**

Créer `backend/services/labs/data_prep/packager.py` :

```python
from pathlib import Path


def package_image_classification(
    images: list, labels: list, class_names: list, out_dir: Path
) -> int:
    from datasets import ClassLabel, Dataset, DatasetDict, Features
    from datasets import Image as HFImage

    features = Features({"image": HFImage(), "label": ClassLabel(names=list(class_names))})
    ds = Dataset.from_dict({"image": list(images), "label": list(labels)}, features=features)
    DatasetDict({"train": ds}).save_to_disk(str(out_dir))
    return len(ds)


def package_texts(
    texts: list,
    labels: list | None = None,
    class_names: list | None = None,
    *,
    out_dir: Path,
) -> int:
    from datasets import ClassLabel, Dataset, DatasetDict, Features, Value

    if labels is not None:
        features = Features(
            {"text": Value("string"), "label": ClassLabel(names=list(class_names))}
        )
        data = {"text": list(texts), "label": list(labels)}
    else:
        features = Features({"text": Value("string")})
        data = {"text": list(texts)}
    ds = Dataset.from_dict(data, features=features)
    DatasetDict({"train": ds}).save_to_disk(str(out_dir))
    return len(ds)
```

- [ ] **Step 4: Vérifier le passage**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v
```

Expected: 22 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/labs/data_prep/packager.py backend/tests/test_labs_data_prep.py
git commit -m "feat(labs): data-prep — empaquetage HF DatasetDict (image|text + label, octets embarqués)"
```

---

### Task 5: Pipeline — orchestration, staging, zip, progression (`pipeline.py`)

**Files:**
- Create: `backend/services/labs/data_prep/pipeline.py`
- Test: `backend/tests/test_labs_data_prep.py` (ajout)

**Interfaces:**
- Consumes: tout ce qui précède (`cleaner`, `converters`, `scanner`, `packager`) + `settings` de `core.config` + le modèle `Dataset`.
- Produces (importés par la tâche 6 — routes) :
  - `PROGRESS: dict[str, dict]` — clé = dataset_id, valeur `{"stage","done","total","message"}` ; stages : `"analyse"`, `"conversion"`, `"empaquetage"`, `"terminé"`, `"erreur"`.
  - `staging_root() -> Path` (= `settings.data_dir / "staging"`) · `purge_staging() -> None`
  - `sanitize_relpath(raw: str, fallback: str) -> Path` — chemin relatif sûr (composants `..`/vides rejetés)
  - `resolve_source(prep_id: str | None, local_path: str | None) -> Path` — lève `ValueError` (message utilisateur) si introuvable
  - `extract_archives(root: Path) -> None` — décompresse chaque `.zip` sur place (garde anti zip-slip), supprime le `.zip`
  - `analyze_source(source: Path) -> dict` (coroutine)
  - `prepare_dataset(db_id: str, source: Path, options: dict, db_session, cleanup_staging: bool = False) -> None` (coroutine, même contrat que `dataset_manager.process_upload` : met à jour l'enregistrement `Dataset` en fin de course). `options` : `{"image_size": int, "text_column": str|None, "label_column": str|None}`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `backend/tests/test_labs_data_prep.py` :

```python
# ── Pipeline (unitaire, sans HTTP ni DB) ─────────────────────────────────────


def test_sanitize_relpath_blocks_traversal():
    from pathlib import Path

    from services.labs.data_prep.pipeline import sanitize_relpath

    assert sanitize_relpath("classA/../../etc/passwd", "f") == Path("classA/etc/passwd")
    assert sanitize_relpath("..\\..\\win", "f") == Path("win")
    assert sanitize_relpath("", "fallback_0") == Path("fallback_0")
    assert sanitize_relpath("chats/1.png", "f") == Path("chats/1.png")


def test_extract_archives_guards_zip_slip(tmp_path):
    import zipfile

    from services.labs.data_prep.pipeline import extract_archives

    zp = tmp_path / "archive.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("inner/ok.txt", "contenu sain")
        zf.writestr("../evil.txt", "hors du dossier")
    extract_archives(tmp_path)
    assert not zp.exists()
    assert (tmp_path / "archive" / "inner" / "ok.txt").read_text(encoding="utf-8") == "contenu sain"
    assert not (tmp_path.parent / "evil.txt").exists()


def test_resolve_source_errors():
    from services.labs.data_prep.pipeline import resolve_source

    with pytest.raises(ValueError):
        resolve_source(None, None)
    with pytest.raises(ValueError):
        resolve_source("prep-inexistant", None)
    with pytest.raises(ValueError):
        resolve_source(None, "Z:/dossier/qui/nexiste/pas")


def test_run_pipeline_images_end_to_end(tmp_path):
    from datasets import load_from_disk

    from core.config import settings
    from services.labs.data_prep.pipeline import _run_pipeline

    for i in range(2):
        _make_image(tmp_path / "chats" / f"c{i}.png", color=(255, i * 90, 0))
        _make_image(tmp_path / "chiens" / f"d{i}.png", color=(0, i * 90, 255))
    _make_image(tmp_path / "chats" / "doublon.png", color=(255, 0, 0))

    db_id = "test-prep-img"
    result = _run_pipeline(db_id, tmp_path, {"image_size": 32})
    try:
        assert result["task_type"] == "classification"
        assert result["num_classes"] == 2
        assert result["class_names"] == ["chats", "chiens"]
        assert result["num_samples"] == 4  # doublon exact écarté
        assert result["size_bytes"] > 0

        split = load_from_disk(result["local_path"])["train"]
        assert {im.size for im in split["image"]} == {(32, 32)}
    finally:
        import shutil

        shutil.rmtree(settings.datasets_dir / db_id, ignore_errors=True)


def test_run_pipeline_corpus_and_errors(tmp_path):
    from core.config import settings
    from services.labs.data_prep.pipeline import _run_pipeline

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "un.txt").write_text("document numéro un", encoding="utf-8")
    (corpus / "deux.txt").write_text("document numéro deux", encoding="utf-8")
    (corpus / "vide.txt").write_text("   \n  ", encoding="utf-8")

    db_id = "test-prep-corpus"
    result = _run_pipeline(db_id, corpus, {})
    try:
        assert result["task_type"] == "nlp"
        assert result["num_samples"] == 2
        assert result["num_classes"] == 0
    finally:
        import shutil

        shutil.rmtree(settings.datasets_dir / db_id, ignore_errors=True)

    vide = tmp_path / "vide"
    vide.mkdir()
    with pytest.raises(ValueError):
        _run_pipeline("test-prep-vide", vide, {})
```

- [ ] **Step 2: Vérifier l'échec**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v -k "pipeline or sanitize or archives or resolve"
```

Expected: 5 FAILED (`ModuleNotFoundError` sur `pipeline`).

- [ ] **Step 3: Implémenter**

Créer `backend/services/labs/data_prep/pipeline.py` :

```python
import asyncio
import io
import logging
import re
import shutil
import zipfile
from pathlib import Path

from core.config import settings
from services.labs.data_prep.cleaner import clean_text, content_hash
from services.labs.data_prep.converters import ConversionError, extract_text, normalize_image
from services.labs.data_prep.packager import package_image_classification, package_texts
from services.labs.data_prep.scanner import read_tabular, scan_full

logger = logging.getLogger(__name__)

PROGRESS: dict = {}

_UNUSABLE = {
    "empty": "Aucun fichier exploitable trouvé dans ce dépôt",
    "unlabeled_images": (
        "Images sans étiquettes : rangez-les dans des sous-dossiers (un par classe) "
        "puis relancez l'analyse"
    ),
}


def set_progress(key: str, stage: str, done: int = 0, total: int = 0, message: str = "") -> None:
    PROGRESS[key] = {"stage": stage, "done": done, "total": total, "message": message}


def staging_root() -> Path:
    return settings.data_dir / "staging"


def purge_staging() -> None:
    shutil.rmtree(staging_root(), ignore_errors=True)


def sanitize_relpath(raw: str, fallback: str) -> Path:
    parts = [
        Path(c).name
        for c in re.split(r"[\\/]+", raw or "")
        if Path(c).name not in ("", ".", "..")
    ]
    return Path(*parts) if parts else Path(fallback)


def resolve_source(prep_id, local_path) -> Path:
    if prep_id:
        source = staging_root() / Path(prep_id).name
        if not source.is_dir():
            raise ValueError("Dépôt introuvable — téléversez à nouveau vos fichiers")
        return source
    if local_path:
        source = Path(local_path).expanduser()
        if not source.is_dir():
            raise ValueError(f"Dossier introuvable: {local_path}")
        return source
    raise ValueError("prep_id ou local_path requis")


def extract_archives(root: Path) -> None:
    for zip_path in list(root.rglob("*.zip")):
        if not zipfile.is_zipfile(zip_path):
            continue
        dest = zip_path.parent / zip_path.stem
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                target = dest / member.filename
                # Anti zip-slip: toute entrée qui s'échapperait du dossier est ignorée.
                if not target.resolve().is_relative_to(dest.resolve()):
                    continue
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))
        zip_path.unlink()


async def analyze_source(source: Path) -> dict:
    from services.labs.data_prep.scanner import scan

    report = await asyncio.get_running_loop().run_in_executor(None, scan, source)
    return report.to_dict()


async def prepare_dataset(
    db_id: str, source: Path, options: dict, db_session, cleanup_staging: bool = False
) -> None:
    from sqlalchemy import select

    from models.dataset import Dataset

    async def _update(status: str, error: str = "", **fields) -> None:
        async with db_session() as db:
            result = await db.execute(select(Dataset).where(Dataset.id == db_id))
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = status
                if error:
                    rec.error_message = error
                for k, v in fields.items():
                    setattr(rec, k, v)
                await db.commit()

    set_progress(db_id, "analyse")
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, _run_pipeline, db_id, Path(source), dict(options or {})
        )
        await _update("ready", **result)
        set_progress(db_id, "terminé", result["num_samples"], result["num_samples"])
    except Exception as exc:
        logger.exception(f"Préparation du dataset {db_id} échouée: {exc}")
        await _update("error", error=str(exc))
        set_progress(db_id, "erreur", message=str(exc))
    finally:
        if cleanup_staging:
            shutil.rmtree(Path(source), ignore_errors=True)


def _run_pipeline(db_id: str, source: Path, options: dict) -> dict:
    report, usable = scan_full(source)
    out_dir = settings.datasets_dir / db_id

    if report.kind == "image_classification":
        num, classes = _prepare_images(db_id, usable, report, int(options.get("image_size") or 64), out_dir)
        task_type = "classification"
    elif report.kind == "text_classification":
        num, classes = _prepare_texts(db_id, usable, report.classes, out_dir)
        task_type = "classification"
    elif report.kind == "text_corpus":
        num, classes = _prepare_texts(db_id, usable, None, out_dir)
        task_type = "nlp"
    elif report.kind == "tabular":
        num, classes = _prepare_tabular(db_id, usable, report, options, out_dir)
        task_type = "classification" if classes else "nlp"
    else:
        raise ValueError(_UNUSABLE.get(report.kind, "Aucune donnée exploitable dans ce dépôt"))

    size_bytes = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    return {
        "local_path": str(out_dir),
        "num_samples": num,
        "num_classes": len(classes),
        "class_names": classes or None,
        "size_bytes": size_bytes,
        "task_type": task_type,
    }


def _prepare_images(db_id, usable, report, image_size, out_dir):
    class_index = {name: i for i, name in enumerate(report.classes)}
    seen: set = set()
    images, labels = [], []
    total = len(usable)
    for i, uf in enumerate(usable):
        set_progress(db_id, "conversion", i + 1, total, uf.path.name)
        try:
            digest = content_hash(uf.path.read_bytes())
            if digest in seen:
                continue
            seen.add(digest)
            img = normalize_image(uf.path, image_size)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=95)
            images.append({"bytes": buf.getvalue(), "path": f"{len(images):07d}.jpg"})
            labels.append(class_index[uf.label])
        except (ConversionError, OSError) as exc:
            logger.warning(f"Image écartée ({uf.path.name}): {exc}")
    if not images:
        raise ValueError("Aucune image exploitable après conversion")
    set_progress(db_id, "empaquetage", total, total)
    num = package_image_classification(images, labels, report.classes, out_dir)
    return num, list(report.classes)


def _prepare_texts(db_id, usable, classes, out_dir):
    class_index = {name: i for i, name in enumerate(classes)} if classes else None
    seen: set = set()
    texts, labels = [], []
    total = len(usable)
    for i, uf in enumerate(usable):
        set_progress(db_id, "conversion", i + 1, total, uf.path.name)
        try:
            text = clean_text(extract_text(uf.path, uf.kind))
        except ConversionError as exc:
            logger.warning(f"Document écarté ({uf.path.name}): {exc}")
            continue
        if not text:
            continue
        digest = content_hash(text)
        if digest in seen:
            continue
        seen.add(digest)
        texts.append(text)
        if class_index is not None:
            labels.append(class_index[uf.label])
    if not texts:
        raise ValueError("Aucun texte exploitable après conversion et nettoyage")
    set_progress(db_id, "empaquetage", total, total)
    if class_index is not None:
        num = package_texts(texts, labels, list(classes), out_dir=out_dir)
        return num, list(classes)
    num = package_texts(texts, out_dir=out_dir)
    return num, []


def _prepare_tabular(db_id, usable, report, options, out_dir):
    info = report.tabular or {}
    text_col = options.get("text_column") or info.get("suggested_text_column")
    label_col = options.get("label_column") or info.get("suggested_label_column")
    if not text_col:
        raise ValueError("Aucune colonne de texte sélectionnée")

    tab_file = next(uf.path for uf in usable if uf.kind == "tabular")
    columns, rows = read_tabular(tab_file)
    if text_col not in columns:
        raise ValueError(f"Colonne texte inconnue: {text_col}")
    if label_col and label_col not in columns:
        raise ValueError(f"Colonne label inconnue: {label_col}")

    seen: set = set()
    texts, raw_labels = [], []
    total = len(rows)
    for i, row in enumerate(rows):
        if i % 200 == 0:
            set_progress(db_id, "conversion", i, total, tab_file.name)
        text = clean_text(str(row.get(text_col, "")))
        if not text:
            continue
        digest = content_hash(text)
        if digest in seen:
            continue
        seen.add(digest)
        texts.append(text)
        if label_col:
            raw_labels.append(str(row.get(label_col, "")))
    if not texts:
        raise ValueError("Aucun texte exploitable dans le fichier tabulaire")

    set_progress(db_id, "empaquetage", total, total)
    if label_col:
        classes = sorted(set(raw_labels))
        index = {c: i for i, c in enumerate(classes)}
        num = package_texts(texts, [index[la] for la in raw_labels], classes, out_dir=out_dir)
        return num, classes
    num = package_texts(texts, out_dir=out_dir)
    return num, []
```

- [ ] **Step 4: Vérifier le passage**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v
```

Expected: 27 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/labs/data_prep/pipeline.py backend/tests/test_labs_data_prep.py
git commit -m "feat(labs): data-prep — pipeline complet (staging, zip, progression, orchestration)"
```

---

### Task 6: Routes API + purge du staging au démarrage de labs-app

**Files:**
- Modify: `backend/api/routes/labs.py` (nouvelle section après le bloc « Datasets », c.-à-d. après la fonction `delete_dataset`, ligne ~160)
- Modify: `labs-app/main.py` (fonction `lifespan`, ligne ~86)
- Test: `backend/tests/test_labs_data_prep.py` (ajout)

**Interfaces:**
- Consumes: `pipeline` (tâche 5) : `PROGRESS`, `analyze_source`, `extract_archives`, `prepare_dataset`, `resolve_source`, `sanitize_relpath`, `staging_root`, `purge_staging`.
- Produces (consommés par l'UI, tâche 7) :
  - `POST /labs/data-prep/upload` — multipart `files` (+ champ `paths` répété, un par fichier, chemin relatif) → `{"prep_id": str, "num_files": int}`
  - `POST /labs/data-prep/analyze` — JSON `{"prep_id"?, "local_path"?}` → rapport (`AnalysisReport.to_dict()`) ; 400 si source introuvable
  - `POST /labs/data-prep/prepare` — JSON `{"prep_id"?, "local_path"?, "name", "image_size"=64, "text_column"?, "label_column"?}` → `{"id": dataset_id, "status": "processing"}` ; 422 si `image_size ∉ {32,64,128,224}` ou nom vide ; 400 si source introuvable
  - `GET /labs/data-prep/progress/{dataset_id}` → `{"stage","done","total","message"}` (stage `"inconnu"` si pas de préparation en mémoire)
- Le router labs est déjà inclus par les deux apps : **aucun câblage** dans `main.py` ni `labs-app/main.py` pour les routes.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `backend/tests/test_labs_data_prep.py` (le fixture `client` reprend le pattern de `test_labs_tokenizers.py`) :

```python
# ── Routes ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as c:
        yield c


def _wait_dataset(client, ds_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/labs/datasets/{ds_id}").json()
        if body["status"] in ("ready", "error"):
            return body
        time.sleep(0.3)
    pytest.fail(f"timeout: dataset {ds_id} toujours en préparation")


def test_analyze_local_path_missing_400(client):
    r = client.post("/api/v1/labs/data-prep/analyze", json={"local_path": "Z:/nulle/part"})
    assert r.status_code == 400
    r = client.post("/api/v1/labs/data-prep/analyze", json={})
    assert r.status_code == 400


def test_prepare_validation_errors(client, tmp_path):
    (tmp_path / "a.txt").write_text("texte", encoding="utf-8")
    r = client.post(
        "/api/v1/labs/data-prep/prepare",
        json={"local_path": str(tmp_path), "name": "x", "image_size": 99},
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/labs/data-prep/prepare",
        json={"local_path": str(tmp_path), "name": "   "},
    )
    assert r.status_code == 422


def test_progress_unknown_id(client):
    r = client.get("/api/v1/labs/data-prep/progress/inconnu")
    assert r.status_code == 200
    assert r.json()["stage"] == "inconnu"


def test_upload_analyze_prepare_full_flow(client):
    files = [
        ("files", ("a.txt", io.BytesIO("avis positif super".encode()), "text/plain")),
        ("files", ("b.txt", io.BytesIO("avis positif génial".encode()), "text/plain")),
        ("files", ("c.txt", io.BytesIO("avis négatif nul".encode()), "text/plain")),
        ("files", ("d.txt", io.BytesIO("avis négatif décevant".encode()), "text/plain")),
    ]
    paths = ["positif/a.txt", "positif/b.txt", "negatif/c.txt", "negatif/d.txt"]
    r = client.post("/api/v1/labs/data-prep/upload", files=files, data={"paths": paths})
    assert r.status_code == 200
    prep_id = r.json()["prep_id"]
    assert r.json()["num_files"] == 4

    r = client.post("/api/v1/labs/data-prep/analyze", json={"prep_id": prep_id})
    assert r.status_code == 200
    report = r.json()
    assert report["kind"] == "text_classification"
    assert report["classes"] == ["negatif", "positif"]
    assert report["num_usable"] == 4

    r = client.post(
        "/api/v1/labs/data-prep/prepare",
        json={"prep_id": prep_id, "name": "avis-prepares"},
    )
    assert r.status_code == 200
    ds_id = r.json()["id"]

    ds = _wait_dataset(client, ds_id)
    assert ds["status"] == "ready", ds.get("error_message")
    assert ds["task_type"] == "classification"
    assert ds["num_classes"] == 2
    assert ds["class_names"] == ["negatif", "positif"]
    assert ds["num_samples"] == 4
    assert ds["size_bytes"] > 0

    from datasets import load_from_disk

    split = load_from_disk(ds["local_path"])["train"]
    assert set(split.column_names) == {"text", "label"}

    r = client.get(f"/api/v1/labs/data-prep/progress/{ds_id}")
    assert r.json()["stage"] == "terminé"

    assert client.delete(f"/api/v1/labs/datasets/{ds_id}").status_code == 200


def test_prepare_local_path_images_flow(client, tmp_path):
    for i in range(2):
        _make_image(tmp_path / "rouge" / f"r{i}.png", color=(255, 40 * i, 0))
        _make_image(tmp_path / "bleu" / f"b{i}.png", color=(0, 40 * i, 255))

    r = client.post("/api/v1/labs/data-prep/analyze", json={"local_path": str(tmp_path)})
    assert r.json()["kind"] == "image_classification"

    r = client.post(
        "/api/v1/labs/data-prep/prepare",
        json={"local_path": str(tmp_path), "name": "couleurs", "image_size": 32},
    )
    ds_id = r.json()["id"]
    ds = _wait_dataset(client, ds_id)
    assert ds["status"] == "ready", ds.get("error_message")
    assert ds["num_samples"] == 4

    from datasets import load_from_disk

    split = load_from_disk(ds["local_path"])["train"]
    assert {im.size for im in split["image"]} == {(32, 32)}

    assert client.delete(f"/api/v1/labs/datasets/{ds_id}").status_code == 200
```

- [ ] **Step 2: Vérifier l'échec**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v -k "analyze or prepare or progress or full_flow"
```

Expected: 5 FAILED avec des 404 (routes inexistantes).

- [ ] **Step 3: Implémenter les routes**

Dans `backend/api/routes/labs.py`, insérer après la fonction `delete_dataset` (avant la section `# ── Tokenizers`) :

```python
# ── Préparation de données (data prep) ───────────────────────────────────────

class DataPrepSourceRequest(BaseModel):
    prep_id: Optional[str] = None
    local_path: Optional[str] = None


class DataPrepPrepareRequest(DataPrepSourceRequest):
    name: str
    image_size: int = 64
    text_column: Optional[str] = None
    label_column: Optional[str] = None


@router.post("/data-prep/upload")
async def data_prep_upload(
    files: List[UploadFile] = File(...),
    paths: Optional[List[str]] = Form(None),
):
    import asyncio
    import uuid as _uuid

    from services.labs.data_prep.pipeline import (
        extract_archives,
        sanitize_relpath,
        staging_root,
    )

    prep_id = str(_uuid.uuid4())
    dest = staging_root() / prep_id
    dest.mkdir(parents=True, exist_ok=True)

    rels = paths if paths and len(paths) == len(files) else [f.filename or "" for f in files]
    for i, (f, rel) in enumerate(zip(files, rels)):
        target = dest / sanitize_relpath(rel, f"fichier_{i}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(await f.read())

    await asyncio.get_running_loop().run_in_executor(None, extract_archives, dest)
    return {"prep_id": prep_id, "num_files": len(files)}


@router.post("/data-prep/analyze")
async def data_prep_analyze(req: DataPrepSourceRequest):
    from services.labs.data_prep.pipeline import analyze_source, resolve_source

    try:
        source = resolve_source(req.prep_id, req.local_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return await analyze_source(source)


@router.post("/data-prep/prepare")
async def data_prep_prepare(req: DataPrepPrepareRequest, db: AsyncSession = Depends(get_db)):
    import asyncio

    from services.labs.data_prep.pipeline import prepare_dataset, resolve_source

    if req.image_size not in (32, 64, 128, 224):
        raise HTTPException(status_code=422, detail="image_size doit être 32, 64, 128 ou 224")
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="Nom du dataset requis")
    try:
        source = resolve_source(req.prep_id, req.local_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    ds_id = str(uuid.uuid4())
    record = Dataset(
        id=ds_id,
        name=req.name.strip(),
        source="upload",
        source_identifier=req.local_path or "dépôt téléversé",
        task_type="classification",
        status="downloading",
    )
    db.add(record)
    await db.commit()

    options = {
        "image_size": req.image_size,
        "text_column": req.text_column,
        "label_column": req.label_column,
    }
    _track_task(
        asyncio.create_task(
            prepare_dataset(
                ds_id, source, options, AsyncSessionLocal,
                cleanup_staging=req.prep_id is not None,
            )
        )
    )
    return {"id": ds_id, "status": "processing"}


@router.get("/data-prep/progress/{dataset_id}")
async def data_prep_progress(dataset_id: str):
    from services.labs.data_prep.pipeline import PROGRESS

    return PROGRESS.get(
        dataset_id, {"stage": "inconnu", "done": 0, "total": 0, "message": ""}
    )
```

Note : `uuid`, `BaseModel`, `Optional`, `List`, `File`, `Form`, `UploadFile`, `Dataset`, `AsyncSessionLocal`, `get_db`, `_track_task` sont déjà importés/définis en haut de `labs.py` — ne pas les réimporter.

- [ ] **Step 4: Purge du staging au démarrage de labs-app**

Dans `labs-app/main.py`, fonction `lifespan` (ligne ~86), ajouter après `await _recover_orphaned_records()` :

```python
    from services.labs.data_prep.pipeline import purge_staging

    purge_staging()
```

- [ ] **Step 5: Vérifier le passage**

```bash
cd backend && python -m pytest tests/test_labs_data_prep.py -v
```

Expected: 33 PASSED. Puis la suite complète :

```bash
make test
```

Expected: tout vert (aucune régression sur les autres fichiers de tests).

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes/labs.py labs-app/main.py backend/tests/test_labs_data_prep.py
git commit -m "feat(labs): data-prep — routes upload/analyze/prepare/progress + purge staging"
```

---

### Task 7: UI labs-app — vue « Préparer » (dropzone, rapport, progression)

**Files:**
- Modify: `labs-app/static/index.html` (nav ligne ~16, nouvelle section après `view-datasets` ligne ~98)
- Modify: `labs-app/static/app.js` (VIEWS ligne 235, `route()` ligne 237, nouvelles fonctions après la section Datasets ligne ~672, bindings en fin de fichier ligne ~860)
- Modify: `labs-app/static/style.css` (ajout en fin de fichier)
- Modify: `labs-app/README.md` (liste des fonctionnalités)

**Interfaces:**
- Consumes: les 4 endpoints de la tâche 6 (mêmes chemins, préfixés `/api/v1` par la constante `API` de `app.js`).
- Produces: rien (feuille de l'arbre).

- [ ] **Step 1: HTML — nav + section**

Dans `labs-app/static/index.html`, après la ligne `<a href="#/datasets" ...>` (ligne 16), ajouter :

```html
    <a href="#/prep" data-view="prep">📦 Préparer</a>
```

Après la section `view-datasets` (ligne ~98, après son `</section>`), ajouter :

```html
    <section class="view" id="view-prep">
      <h1>Préparer des données</h1>
      <p class="subtitle">Déposez n'importe quoi — dossiers, images, documents, CSV, zip — l'app trie, convertit, nettoie et emballe le tout en dataset prêt à entraîner.</p>
      <div class="card">
        <h2 style="margin-top:0">1 · Dépôt</h2>
        <div class="dropzone" id="prep-drop">
          <p>Glissez ici des fichiers ou un dossier entier</p>
          <div class="drop-actions">
            <button class="ghost" id="btn-prep-pick-files">Choisir des fichiers</button>
            <button class="ghost" id="btn-prep-pick-dir">Choisir un dossier</button>
          </div>
          <input type="file" id="prep-files" multiple hidden />
          <input type="file" id="prep-dir" webkitdirectory hidden />
        </div>
        <label>… ou chemin d'un dossier local <span class="help">— lecture directe sur disque, rien n'est copié</span></label>
        <div class="grid2">
          <input type="text" id="prep-path" placeholder="C:\Users\moi\mes-donnees" />
          <button id="btn-prep-analyze-path">🔍 Analyser ce dossier</button>
        </div>
        <p class="help" id="prep-upload-status"></p>
      </div>
      <div class="card" id="prep-report-card" style="display:none">
        <h2 style="margin-top:0">2 · Rapport d'analyse</h2>
        <div id="prep-report"></div>
        <div class="grid3">
          <div><label>Nom du dataset</label><input type="text" id="prep-name" placeholder="mon-dataset" /></div>
          <div id="prep-imgsize-wrap"><label>Taille des images (px)</label>
            <select id="prep-imgsize"><option>32</option><option selected>64</option><option>128</option><option>224</option></select></div>
          <div id="prep-cols-wrap" style="display:none">
            <label>Colonne texte</label><select id="prep-text-col"></select>
            <label>Colonne label</label><select id="prep-label-col"></select>
          </div>
        </div>
        <div style="margin-top:14px"><button id="btn-prep-start">⚙ Préparer</button></div>
      </div>
      <div class="card" id="prep-progress-card" style="display:none">
        <h2 style="margin-top:0">3 · Préparation</h2>
        <div class="progress-track"><div class="progress-fill" id="prep-progress-fill"></div></div>
        <p class="help" id="prep-progress-text"></p>
      </div>
    </section>
```

- [ ] **Step 2: CSS**

Ajouter à la fin de `labs-app/static/style.css` :

```css
/* ── Préparation de données ──────────────────────────── */
.dropzone {
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 28px;
  text-align: center;
  color: var(--muted);
  margin-bottom: 14px;
}
.dropzone.drag { border-color: var(--accent); background: var(--surface-2); color: var(--ink-2); }
.drop-actions { margin-top: 10px; display: flex; gap: 10px; justify-content: center; }
.progress-track {
  height: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}
.progress-fill { height: 100%; width: 0%; background: var(--accent); transition: width 0.4s; }
.prep-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.prep-report-kind { color: var(--ink); font-size: 15px; font-weight: 600; margin-bottom: 6px; }
.prep-ignored { margin-top: 10px; }
.prep-ignored summary { cursor: pointer; color: var(--muted); }
.prep-ignored li { color: var(--muted); font-size: 12px; margin-left: 18px; }
```

- [ ] **Step 3: JS — état, routing, logique**

Dans `labs-app/static/app.js` :

1. Ligne 227, ajouter au `state` :

```js
  prep: { prepId: null, localPath: null, report: null, pollTimer: null },
```

2. Ligne 235, ajouter `'prep'` :

```js
const VIEWS = ['runs', 'new', 'datasets', 'prep', 'tokenizers', 'archs', 'hardware', 'console'];
```

3. Après la fonction `uploadDataset()` (ligne ~672), insérer :

```js
/* ── Préparation de données ───────────────────────────── */

const PREP_KINDS = {
  image_classification: "🖼 Classification d'images",
  text_classification: '📄 Classification de texte',
  text_corpus: '📚 Corpus de texte (NLP / tokenizers)',
  tabular: '📊 Tabulaire → classification de texte',
  unlabeled_images: '⚠ Images sans étiquettes',
  empty: '∅ Rien d\'exploitable',
};

async function collectDropped(dataTransfer) {
  const items = [...dataTransfer.items];
  const out = [];
  async function walk(entry, prefix) {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file, rel: prefix + file.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        for (const e of batch) await walk(e, prefix + entry.name + '/');
      } while (batch.length);
    }
  }
  const entries = items.map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...dataTransfer.files].map((f) => ({ file: f, rel: f.name }));
  for (const e of entries) await walk(e, '');
  return out;
}

async function prepUpload(fileEntries) {
  if (!fileEntries.length) { toast('Aucun fichier', true); return; }
  const status = document.getElementById('prep-upload-status');
  status.textContent = `Téléversement de ${fileEntries.length} fichier(s)…`;
  const fd = new FormData();
  for (const { file, rel } of fileEntries) {
    fd.append('files', file);
    fd.append('paths', rel);
  }
  try {
    const r = await api('/labs/data-prep/upload', { method: 'POST', body: fd });
    state.prep = { ...state.prep, prepId: r.prep_id, localPath: null, report: null };
    status.textContent = `${r.num_files} fichier(s) téléversé(s) — analyse…`;
    await prepAnalyze();
    status.textContent = '';
  } catch (e) { status.textContent = ''; toast(e.message, true); }
}

async function prepAnalyzePath() {
  const path = document.getElementById('prep-path').value.trim();
  if (!path) { toast('Indiquez un chemin de dossier', true); return; }
  state.prep = { ...state.prep, prepId: null, localPath: path, report: null };
  try { await prepAnalyze(); } catch (e) { toast(e.message, true); }
}

async function prepAnalyze() {
  const body = state.prep.prepId
    ? { prep_id: state.prep.prepId } : { local_path: state.prep.localPath };
  const report = await api('/labs/data-prep/analyze', {
    method: 'POST', body: JSON.stringify(body),
  });
  state.prep.report = report;
  renderPrepReport(report);
}

function renderPrepReport(rep) {
  const card = document.getElementById('prep-report-card');
  card.style.display = 'block';
  const counts = Object.entries(rep.counts)
    .map(([k, v]) => `${v} ${esc(k)}`).join(' · ') || 'aucun fichier reconnu';
  const conversions = Object.entries(rep.conversions)
    .map(([k, v]) => `${v} × ${esc(k)}`).join(' · ');
  const classes = rep.classes.length
    ? `<div class="prep-chips">${rep.classes.map((c) => `<span class="chip ready">${esc(c)}</span>`).join('')}</div>` : '';
  const warnings = rep.warnings.map((w) => `<p style="color:var(--warning)">⚠ ${esc(w)}</p>`).join('');
  const ignored = rep.ignored.length
    ? `<details class="prep-ignored"><summary>${rep.ignored.length} fichier(s) ignoré(s)</summary>
       <ul>${rep.ignored.slice(0, 200).map((i) => `<li>${esc(i.path)} — ${esc(i.reason)}</li>`).join('')}</ul></details>` : '';

  document.getElementById('prep-report').innerHTML = `
    <div class="prep-report-kind">${PREP_KINDS[rep.kind] || esc(rep.kind)}</div>
    <p>${rep.num_usable} fichier(s) exploitable(s) sur ${rep.num_files} — ${counts}</p>
    ${conversions ? `<p>Conversions prévues : ${conversions}</p>` : ''}
    ${classes}${warnings}${ignored}`;

  document.getElementById('prep-imgsize-wrap').style.display =
    rep.kind === 'image_classification' ? 'block' : 'none';
  const colsWrap = document.getElementById('prep-cols-wrap');
  colsWrap.style.display = rep.kind === 'tabular' ? 'block' : 'none';
  if (rep.kind === 'tabular' && rep.tabular) {
    const opts = (sel) => rep.tabular.columns
      .map((c) => `<option value="${esc(c)}" ${c === sel ? 'selected' : ''}>${esc(c)}</option>`).join('');
    document.getElementById('prep-text-col').innerHTML = opts(rep.tabular.suggested_text_column);
    document.getElementById('prep-label-col').innerHTML =
      '<option value="">— aucune (corpus) —</option>' + opts(rep.tabular.suggested_label_column);
  }
  document.getElementById('btn-prep-start').disabled =
    rep.kind === 'empty' || rep.kind === 'unlabeled_images';
}

async function prepStart() {
  const name = document.getElementById('prep-name').value.trim();
  if (!name) { toast('Nom du dataset requis', true); return; }
  const rep = state.prep.report;
  const body = state.prep.prepId
    ? { prep_id: state.prep.prepId } : { local_path: state.prep.localPath };
  body.name = name;
  body.image_size = parseInt(document.getElementById('prep-imgsize').value, 10);
  if (rep && rep.kind === 'tabular') {
    body.text_column = document.getElementById('prep-text-col').value || null;
    body.label_column = document.getElementById('prep-label-col').value || null;
  }
  try {
    const r = await api('/labs/data-prep/prepare', { method: 'POST', body: JSON.stringify(body) });
    document.getElementById('prep-progress-card').style.display = 'block';
    pollPrep(r.id);
  } catch (e) { toast(e.message, true); }
}

async function pollPrep(datasetId) {
  clearTimeout(state.prep.pollTimer);
  let p;
  try { p = await api('/labs/data-prep/progress/' + datasetId); }
  catch { state.prep.pollTimer = setTimeout(() => pollPrep(datasetId), 1500); return; }

  const fill = document.getElementById('prep-progress-fill');
  const text = document.getElementById('prep-progress-text');
  const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
  fill.style.width = (p.stage === 'terminé' ? 100 : pct) + '%';
  text.textContent = `${p.stage}${p.total ? ` — ${p.done}/${p.total}` : ''}${p.message ? ' · ' + p.message : ''}`;

  if (p.stage === 'terminé') {
    toast('Dataset prêt ! Il apparaît dans « Datasets ».');
    location.hash = '#/datasets';
  } else if (p.stage === 'erreur') {
    toast(p.message || 'La préparation a échoué', true);
  } else {
    state.prep.pollTimer = setTimeout(() => pollPrep(datasetId), 1000);
  }
}
```

4. En fin de fichier (près de `document.getElementById('btn-ds-upload').onclick = uploadDataset;`, ligne ~860), ajouter :

```js
/* Préparation de données */
const prepDrop = document.getElementById('prep-drop');
prepDrop.addEventListener('dragover', (e) => { e.preventDefault(); prepDrop.classList.add('drag'); });
prepDrop.addEventListener('dragleave', () => prepDrop.classList.remove('drag'));
prepDrop.addEventListener('drop', async (e) => {
  e.preventDefault();
  prepDrop.classList.remove('drag');
  prepUpload(await collectDropped(e.dataTransfer));
});
document.getElementById('btn-prep-pick-files').onclick = () => document.getElementById('prep-files').click();
document.getElementById('btn-prep-pick-dir').onclick = () => document.getElementById('prep-dir').click();
document.getElementById('prep-files').onchange = (e) =>
  prepUpload([...e.target.files].map((f) => ({ file: f, rel: f.webkitRelativePath || f.name })));
document.getElementById('prep-dir').onchange = (e) =>
  prepUpload([...e.target.files].map((f) => ({ file: f, rel: f.webkitRelativePath || f.name })));
document.getElementById('btn-prep-analyze-path').onclick = prepAnalyzePath;
document.getElementById('btn-prep-start').onclick = prepStart;
```

- [ ] **Step 4: README**

Dans `labs-app/README.md`, section « Fonctionnalités », ajouter après la puce **Datasets** :

```markdown
- **Préparation A → Z** : déposez un dossier, des fichiers ou un zip (images,
  docs, texte, CSV) — tri par contenu réel, conversion (pdf/docx/rtf/html → txt,
  toute image → jpeg normalisé), nettoyage, dédoublonnage, puis empaquetage en
  dataset Hugging Face directement entraînable. Assistant en 2 étapes :
  rapport d'analyse, puis préparation avec progression en direct.
```

- [ ] **Step 5: Vérification manuelle**

```bash
labs-app/start-labs.bat
```

Puis dans le navigateur (http://localhost:8100, vue « 📦 Préparer ») :
1. Créer un dossier local avec 2 sous-dossiers de quelques images → coller le chemin → « Analyser » → rapport avec 2 classes → « Préparer » → progression → toast → dataset visible dans « Datasets », statut ready.
2. Glisser-déposer 2-3 fichiers .txt → rapport « Corpus de texte » → préparer → ready.
3. Vérifier qu'un run d'entraînement peut sélectionner le dataset préparé.

Expected: les 3 parcours aboutissent sans erreur console (F12).

- [ ] **Step 6: Commit**

```bash
git add labs-app/static/index.html labs-app/static/app.js labs-app/static/style.css labs-app/README.md
git commit -m "feat(labs): UI Préparer — dropzone, chemin local, rapport d'analyse, progression"
```

---

### Task 8: Vérification finale

**Files:**
- Aucun nouveau fichier — lint, tests, vérification bout en bout.

**Interfaces:**
- Consumes: tout.
- Produces: branche prête à merger.

- [ ] **Step 1: Lint**

```bash
make lint-fix
```

Expected: aucune erreur restante (attention ruff I001 dans les imports de fonctions).

- [ ] **Step 2: Suite complète**

```bash
make test
```

Expected: tous les tests passent, y compris `test_labs_data_prep.py` (33 tests) et les suites existantes (aucune régression).

- [ ] **Step 3: Type check**

```bash
make type-check
```

Expected: pas de nouvelle erreur par rapport à l'état d'avant la branche.

- [ ] **Step 4: Vérification end-to-end réelle**

Refaire le parcours manuel de la tâche 7 step 5 si pas encore fait, **plus** : lancer un entraînement CNN sur un dataset d'images préparé (2 classes, image_size 32, 1-2 epochs) et vérifier que les métriques bougent (le trainer consomme le dataset préparé, pas le dataset factice — le log du run ne doit PAS contenir « dataset not parseable » ni « no dataset selected »).

- [ ] **Step 5: Commit final si retouches**

```bash
git add -A && git commit -m "chore(labs): data-prep — lint et retouches finales"
```
