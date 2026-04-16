"""Tests for mneme.config."""

from pathlib import Path

import tomli_w

from mneme.config import MnemeConfig, load_config, save_config


def test_defaults():
    config = MnemeConfig()
    assert config.embedding.model == "BAAI/bge-m3"
    assert config.embedding.provider == "sentence-transformers"
    assert config.search.vector_weight == 0.6
    assert config.search.bm25_weight == 0.4
    assert config.search.top_k == 10
    assert config.chunking.max_tokens == 1000
    assert config.chunking.overlap_tokens == 100
    assert config.server.transport == "stdio"


def test_load_from_toml(tmp_path: Path):
    toml_path = tmp_path / "config.toml"
    data = {
        "vault": {"path": "D:\\Vault\\test"},
        "search": {"top_k": 20},
    }
    with open(toml_path, "wb") as f:
        tomli_w.dump(data, f)

    config = load_config(toml_path)
    assert config.vault.path == "D:\\Vault\\test"
    assert config.search.top_k == 20
    # defaults preserved for unset fields
    assert config.embedding.model == "BAAI/bge-m3"


def test_load_missing_file_returns_defaults(tmp_path: Path):
    config = load_config(tmp_path / "nonexistent.toml")
    assert config.embedding.model == "BAAI/bge-m3"


def test_save_and_reload(tmp_path: Path):
    toml_path = tmp_path / "config.toml"
    original = MnemeConfig(vault={"path": "D:\\my\\vault"}, search={"top_k": 15})
    save_config(original, toml_path)
    reloaded = load_config(toml_path)
    assert reloaded.vault.path == original.vault.path
    assert reloaded.search.top_k == original.search.top_k
    assert reloaded.embedding.model == original.embedding.model


def test_env_var_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MNEME_VAULT__PATH", "/from/env")
    config = MnemeConfig()
    assert config.vault.path == "/from/env"


def test_db_path_default():
    config = MnemeConfig()
    assert config.db_path.name == "mneme.db"


def test_db_path_custom():
    config = MnemeConfig(database={"path": "/custom/path.db"})
    assert config.db_path == Path("/custom/path.db")
