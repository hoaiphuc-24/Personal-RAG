from dataclasses import dataclass
from pathlib import Path
import hashlib
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    provider: str = "demo"
    project_name: str = "Personal AgenticRAG"
    owner_name: str = "You"
    api_key: str = ""
    chat_model: str = "gpt-4o-mini"
    embed_model: str = "text-embedding-3-small"
    data_dir: Path = ROOT / "data"
    chunk_size: int = 900
    chunk_overlap: int = 150
    max_agent_steps: int = 5
    max_upload_mb: int = 10

    def __post_init__(self):
        if self.provider not in {"demo", "openai"}:
            raise ValueError("RAG_PROVIDER must be demo or openai.")
        if self.provider == "openai" and not self.api_key.strip():
            raise ValueError("OPENAI_API_KEY is required in the personal-agentic-rag .env file.")
        if not 200 <= self.chunk_size <= 4000:
            raise ValueError("CHUNK_SIZE must be in the range 200..4000.")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
        if not 1 <= self.max_agent_steps <= 8 or not 1 <= self.max_upload_mb <= 25:
            raise ValueError("MAX_AGENT_STEPS must be 1..8; MAX_UPLOAD_MB must be 1..25.")

    @property
    def embedding_space(self) -> str:
        return "demo-hash-v1" if self.provider == "demo" else f"openai:{self.embed_model}"

    @property
    def db_path(self) -> Path:
        # Separate workspaces prevent mixing incompatible embedding spaces.
        suffix = hashlib.sha256(self.embedding_space.encode()).hexdigest()[:10]
        return self.data_dir / f"workspace-{self.provider}-{suffix}.sqlite3"


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    return Settings(
        provider=os.getenv("RAG_PROVIDER", "demo").strip().lower(),
        project_name=os.getenv("PROJECT_NAME", "Personal AgenticRAG"),
        owner_name=os.getenv("OWNER_NAME", "You"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        embed_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        data_dir=data_dir,
        chunk_size=int(os.getenv("CHUNK_SIZE", "900")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
        max_agent_steps=int(os.getenv("MAX_AGENT_STEPS", "5")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
    )
