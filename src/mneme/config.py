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
    provider: str = "sentence-transformers"  # "sentence-transformers" | "raw-transformers" | "onnx"
    model: str = "BAAI/bge-m3"
    backend: str = "cpu"  # ONNX only: "cpu" | "directml" | "cuda" | "rocm"
    device: str = "auto"  # "auto" | "cpu" | "cuda"
    batch_size: int = 32  # 32-256, higher = faster on GPU (needs VRAM)
    dtype: str = "float16"  # "float32" | "float16" | "bfloat16"


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
    # "stdio" (default) speaks MCP via stdin/stdout for Claude Desktop / Claudian.
    # "streamable-http" exposes MCP over HTTP — long-running server, model pre-warmed.
    transport: str = "stdio"
    # HTTP transport only. Loopback by default; FastMCP also enables
    # DNS-rebinding protection automatically for 127.0.0.1.
    host: str = "127.0.0.1"
    port: int = 8765  # non-standard to avoid conflicts with common dev servers


class RerankingConfig(BaseModel):
    enabled: bool = False  # Opt-in, nicht standardmäßig aktiv
    model: str = "BAAI/bge-reranker-v2-m3"
    top_k: int = 50  # Wie viele Ergebnisse an den Reranker geben
    threshold: float = 0.3  # Ergebnisse unter diesem Score entfernen


class ScoringConfig(BaseModel):
    gars_enabled: bool = False  # Opt-in
    graph_weight: float = 0.3   # 0.0 = nur RRF, 1.0 = nur Graph


class AutoSearchConfig(BaseModel):
    mode: str = "smart"                    # "off" | "smart" | "always"
    claude_md_path: str = "CLAUDE.md"      # Relativ zum Vault-Root
    hook_matchers: list[str] = Field(default_factory=lambda: ["Read"])


class HealthConfig(BaseModel):
    # Users set this per-vault via `mneme update-config health.exclude_patterns`.
    exclude_patterns: list[str] = Field(default_factory=list)


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
    auto_search: AutoSearchConfig = Field(default_factory=AutoSearchConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)

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


class ConfigUpdateError(ValueError):
    """Raised when a config update cannot be applied (unknown key or bad value)."""


# Sections whose values trigger code-loading (embedding/reranking via
# HuggingFace `trust_remote_code`) or network exposure (server.host / port).
# Blocked from the MCP `update_config` tool so prompt-injected notes cannot
# swap a model or push the server off loopback via an LLM tool call.
MCP_FORBIDDEN_SECTIONS: frozenset[str] = frozenset(
    {"embedding", "reranking", "server"}
)


# Per-key value constraints for update_config. Keys not listed here are
# unconstrained beyond their Pydantic type. Ranges are inclusive.
_CONFIG_VALUE_CONSTRAINTS: dict[str, dict] = {
    "vault.path": {"non_empty_str": True},
    "search.vector_weight": {"min": 0.0, "max": 1.0},
    "search.bm25_weight": {"min": 0.0, "max": 1.0},
    "search.top_k": {"min": 1, "max": 100},
    "embedding.batch_size": {"min": 1, "max": 512},
    "chunking.max_tokens": {"min": 50, "max": 8192},
    "chunking.overlap_tokens": {"min": 0, "max": 2048},
    "reranking.threshold": {"min": 0.0, "max": 1.0},
    "reranking.top_k": {"min": 1, "max": 200},
    "scoring.graph_weight": {"min": 0.0, "max": 1.0},
    "health.stale_days": {"min": 1, "max": 3650},
    "server.port": {"min": 1024, "max": 65535},
}


def apply_config_update(
    config: MnemeConfig, key: str, value: str
) -> tuple[str, object, object]:
    """Parse *value* into the existing setting's type and apply it on *config*.

    Returns ``(key, old_value, new_value)``. Raises ``ConfigUpdateError`` for
    invalid keys or out-of-range values. The caller is responsible for
    persisting (save_config) AND for rolling back on save failure — use
    ``(_, old, _) = apply_config_update(...)`` then ``setattr(section, name, old)``
    in the exception handler.
    """
    import json as _json

    parts = key.split(".")
    if len(parts) != 2:
        raise ConfigUpdateError(f"Key must be 'section.setting', got '{key}'")

    section_name, setting_name = parts
    section = getattr(config, section_name, None)
    if section is None:
        raise ConfigUpdateError(f"Unknown section: {section_name}")
    if not hasattr(section, setting_name):
        raise ConfigUpdateError(f"Unknown setting: {key}")

    old_value = getattr(section, setting_name)
    target_type = type(old_value)
    try:
        if target_type is bool:
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                parsed = True
            elif lowered in ("false", "0", "no", "off"):
                parsed = False
            else:
                raise ConfigUpdateError(
                    f"Cannot parse '{value}' as bool. Use true/false, 1/0, yes/no, or on/off."
                )
        elif target_type is int:
            parsed = int(value)
        elif target_type is float:
            parsed = float(value)
        elif target_type is list:
            parsed = _json.loads(value)
            if not isinstance(parsed, list):
                raise ConfigUpdateError(
                    f"Expected a JSON array for '{key}', got {type(parsed).__name__}. "
                    f"Example: '[\"a\",\"b\"]'"
                )
        else:
            parsed = value
    except ConfigUpdateError:
        raise
    except (ValueError, TypeError) as e:
        hint = ""
        if target_type is list:
            hint = " (lists must be JSON arrays, e.g. '[\"a\",\"b\"]')"
        raise ConfigUpdateError(
            f"Cannot parse '{value}' as {target_type.__name__}: {e}{hint}"
        ) from e

    # Range / non-empty validation
    constraints = _CONFIG_VALUE_CONSTRAINTS.get(key)
    if constraints is not None:
        if constraints.get("non_empty_str") and isinstance(parsed, str) and not parsed.strip():
            raise ConfigUpdateError(
                f"{key} must not be empty — an empty value would brick all commands."
            )
        lo = constraints.get("min")
        hi = constraints.get("max")
        if lo is not None and isinstance(parsed, (int, float)) and parsed < lo:
            raise ConfigUpdateError(
                f"{key}={parsed} is below the minimum ({lo})."
            )
        if hi is not None and isinstance(parsed, (int, float)) and parsed > hi:
            raise ConfigUpdateError(
                f"{key}={parsed} is above the maximum ({hi})."
            )

    setattr(section, setting_name, parsed)
    return key, old_value, parsed
