from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Studio"
    debug: bool = False

    # Paths
    data_dir: Path = BASE_DIR / "data"
    images_dir: Path = BASE_DIR / "data" / "images"
    models_dir: Path = BASE_DIR / "data" / "models"
    datasets_dir: Path = BASE_DIR / "data" / "datasets"
    db_path: Path = BASE_DIR / "data" / "db" / "app.db"

    # Database
    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    # Networking / CORS — overridable via CORS_ORIGINS="https://a.com,https://b.com"
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    # Ollama
    ollama_base_url: str = "http://localhost:11434"

    # Hardware / compute
    # Force a torch device (e.g. "cpu", "cuda:1", "mps"); empty = autodetect.
    device_preference: str = ""
    # Opt-in torch.compile for image pipelines (first run is slow to warm up).
    enable_torch_compile: bool = False
    # Live latent previews are decoded through the VAE on every step — cheap on a
    # big GPU but they can dominate runtime on small/CPU setups. Disabled
    # automatically on CPU and throttled elsewhere.
    enable_live_preview: bool = True

    # Image generation
    max_queue_size: int = 50
    max_pipelines_loaded: int = 1
    # Reject obviously oversized generation requests early (megapixels).
    max_image_megapixels: float = 4.2  # ~2048x2048

    # Uploads / safety
    max_upload_mb: int = 512

    # Kaggle (optional)
    kaggle_username: str = ""
    kaggle_key: str = ""

    # HuggingFace (optional, for private/gated models & datasets)
    huggingface_token: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


settings = Settings()


def ensure_dirs() -> None:
    for d in [
        settings.data_dir,
        settings.images_dir,
        settings.models_dir / "diffusion",
        settings.models_dir / "ollama",
        settings.models_dir / "trained",
        settings.datasets_dir,
        settings.db_path.parent,
    ]:
        d.mkdir(parents=True, exist_ok=True)
