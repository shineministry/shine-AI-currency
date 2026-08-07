import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name: str = "ShineFX"
    data_dir: Path
    db_path: Path

    ollama_url: str
    embed_model: str
    chat_model: str

    base_currency: str
    fetch_source: str
    fetch_interval_min: int
    auto_ingest: bool

    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("SHINEFX_DATA_DIR", "data")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "shinefx.db"

        self.ollama_url = os.getenv("SHINEFX_OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.embed_model = os.getenv("SHINEFX_EMBED_MODEL", "nomic-embed-text")
        self.chat_model = os.getenv("SHINEFX_CHAT_MODEL", "llama3.2")

        self.base_currency = os.getenv("SHINEFX_BASE_CURRENCY", "EUR").upper()
        self.fetch_source = os.getenv("SHINEFX_FETCH_SOURCE", "ecb").lower()
        self.fetch_interval_min = int(os.getenv("SHINEFX_FETCH_INTERVAL_MIN", "60"))
        self.auto_ingest = _env_bool("SHINEFX_AUTO_INGEST", True)

    def to_dict(self) -> dict:
        return {
            "app": self.app_name,
            "data_dir": str(self.data_dir),
            "db": str(self.db_path),
            "ollama_url": self.ollama_url,
            "embed_model": self.embed_model,
            "chat_model": self.chat_model,
            "base_currency": self.base_currency,
            "fetch_source": self.fetch_source,
            "fetch_interval_min": self.fetch_interval_min,
            "auto_ingest": self.auto_ingest,
        }


settings = Settings()
