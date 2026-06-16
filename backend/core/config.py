from pathlib import Path
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

    # Ollama
    ollama_base_url: str = "http://localhost:11434"

    # Image generation
    max_queue_size: int = 50
    max_pipelines_loaded: int = 1

    # Kaggle (optional)
    kaggle_username: str = ""
    kaggle_key: str = ""

    # HuggingFace (optional, for private models/datasets)
    huggingface_token: str = ""


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
