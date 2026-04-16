"""Mneme configuration — Pydantic Settings with TOML backend."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import tomli_w
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_config_path() -> Path:
    return Path(platformdirs.user_config_dir("mneme")) / "config.toml"


def _default_db_path() -> Path:
    return Path(platformdirs.user_data_dir("mneme")) / "mneme.db"


class VaultConfig(BaseModel):
    path: str = ""
    glob_patterns: list[str] = Field(default_factory=lambda: ["**/*.md"])
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [".obsidian/**", ".trash/**", ".claude/**"]
    )


class EmbeddingConfig(BaseModel):
    provider: str = "sentence-transformers"
    model: str = "BAAI/bge-m3"


class ChunkingConfig(BaseModel):
    strategy: str = "heading"
    max_tokens: int = 1000
    overlap_tokens: int = 100


class SearchConfig(BaseModel):
    vector_weight: float = 0.6
    bm25_weight: float = 0.4
    top_k: int = 10


class DatabaseConfig(BaseModel):
    path: str = ""


class ServerConfig(BaseModel):
    transport: str = "stdio"


class RerankingConfig(BaseModel):
    enabled: bool = False  # Opt-in, nicht standardmäßig aktiv
    model: str = "BAAI/bge-reranker-v2-m3"
    top_k: int = 50  # Wie viele Ergebnisse an den Reranker geben
    threshold: float = 0.3  # Ergebnisse unter diesem Score entfernen


class ScoringConfig(BaseModel):
    gars_enabled: bool = False  # Opt-in
    graph_weight: float = 0.3   # 0.0 = nur RRF, 1.0 = nur Graph


class MnemeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MNEME_", env_nested_delimiter="__")

    vault: VaultConfig = Field(default_factory=VaultConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    reranking: RerankingConfig = Field(default_factory=RerankingConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)

    @property
    def db_path(self) -> Path:
        if self.database.path:
            return Path(self.database.path)
        return _default_db_path()

    @property
    def vault_path(self) -> Path:
        return Path(self.vault.path)


def config_path() -> Path:
    return _default_config_path()


def load_config(path: Path | None = None) -> MnemeConfig:
    """Load config from TOML file, merged with env vars."""
    toml_path = path or config_path()
    if toml_path.exists():
        import tomllib

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return MnemeConfig(**data)
    return MnemeConfig()


def save_config(config: MnemeConfig, path: Path | None = None) -> Path:
    """Save config to TOML file. Returns the path written to."""
    toml_path = path or config_path()
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(exclude_defaults=False)
    with open(toml_path, "wb") as f:
        tomli_w.dump(data, f)
    return toml_path
