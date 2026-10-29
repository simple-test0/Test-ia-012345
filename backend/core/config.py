from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    # Read backend/.env wherever the server is launched from (then ./.env).
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), ".env"),
        extra="ignore",
    )

    app_name: str = "AI Studio"
    debug: bool = False
    # Serve frontend/dist from the backend when it has been built.
    serve_frontend: bool = True

    # Paths. Only DATA_DIR usually needs setting: the sub-folders derive from it
    # unless they are overridden individually.
    data_dir: Path = BASE_DIR / "data"
    images_dir: Optional[Path] = None
    models_dir: Optional[Path] = None
    datasets_dir: Optional[Path] = None
    db_path: Optional[Path] = None

    @model_validator(mode="after")
    def _derive_paths(self) -> "Settings":
        self.images_dir = self.images_dir or self.data_dir / "images"
        self.models_dir = self.models_dir or self.data_dir / "models"
        self.datasets_dir = self.datasets_dir or self.data_dir / "datasets"
        self.db_path = self.db_path or self.data_dir / "db" / "app.db"
        return self

    # Database
    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    # Extra browser origins allowed by CORS, comma-separated
    # (e.g. "http://192.168.1.20:5173"). Local dev origins are always allowed.
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> List[str]:
        defaults = [
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in (5173, 4173, 3000)
        ]
        extra = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        return defaults + extra

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    # Timeout (s) for one model reply. Large models on CPU can be slow.
    ollama_timeout: float = 300.0

    # Image generation
    max_queue_size: int = 50
    max_pipelines_loaded: int = 1

    # Kaggle (optional)
    kaggle_username: str = ""
    kaggle_key: str = ""

    # HuggingFace (optional, for private models/datasets)
    huggingface_token: str = ""

    # Security: optional shared token. When set, REST requests must send
    # `X-API-Token` and WebSocket connections must pass `?token=...`.
    # Empty (default) keeps the local dev experience open.
    api_token: str = ""

    # Agent code execution. Disabled by default — it runs arbitrary Python.
    # Enable explicitly (and prefer an isolated environment) before use.
    enable_code_executor: bool = False
    code_executor_timeout: int = 15
    code_executor_max_memory_mb: int = 512

    # Hugging Face downloads: refuse if free disk falls below this margin.
    min_free_disk_mb: int = 2048

    # Dataset uploads: maximum total size per upload (MB).
    max_upload_mb: int = 2048


settings = Settings()


def utcnow() -> datetime:
    """Naive UTC timestamp (matches the DB columns; avoids deprecated utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_dirs() -> None:
    for d in [
        settings.data_dir,
        settings.images_dir,
        settings.images_dir / "thumbs",
        settings.models_dir / "diffusion",
        settings.models_dir / "ollama",
        settings.models_dir / "trained",
        settings.datasets_dir,
        settings.db_path.parent,
    ]:
        d.mkdir(parents=True, exist_ok=True)
