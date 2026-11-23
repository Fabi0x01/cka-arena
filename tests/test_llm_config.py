"""Tests for the frontend-editable AI provider configuration."""

from __future__ import annotations

import json

import pytest

from app import llm_client


@pytest.fixture()
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "llm_config.json"
    monkeypatch.setattr("app.config.LLM_CONFIG_PATH", path)
    monkeypatch.delenv("CKA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("CKA_LLM_PROVIDER", raising=False)
    return path


def test_public_config_never_exposes_raw_key(config_file) -> None:
    llm_client.save_config({
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-supersecret-1234",
        "model": "deepseek-chat",
        "model_flash": "deepseek-chat",
    })
    public = llm_client.public_config()
    assert public["has_key"] is True
    assert public["api_key_masked"].endswith("1234")
    assert "sk-supersecret" not in json.dumps(public)
    assert public["source"] == "file"
    assert {p["id"] for p in public["providers"]} >= {"deepseek", "anthropic", "glm_coding"}


def test_save_preserves_key_when_blank_or_masked(config_file) -> None:
    llm_client.save_config({"provider": "deepseek", "api_key": "sk-keepme-9999",
                            "model": "deepseek-chat", "model_flash": "deepseek-chat",
                            "base_url": "https://api.deepseek.com/v1"})
    llm_client.save_config({"provider": "deepseek", "api_key": "",
                            "model": "deepseek-chat", "model_flash": "deepseek-chat",
                            "base_url": "https://api.deepseek.com/v1"})
    assert llm_client.load_config()["api_key"] == "sk-keepme-9999"

    llm_client.save_config({"provider": "deepseek", "api_key": "••••••••9999",
                            "model": "deepseek-chat", "model_flash": "deepseek-chat",
                            "base_url": "https://api.deepseek.com/v1"})
    assert llm_client.load_config()["api_key"] == "sk-keepme-9999"


def test_clear_key_empties_it(config_file) -> None:
    llm_client.save_config({"provider": "deepseek", "api_key": "sk-abc-1234",
                            "model": "deepseek-chat", "model_flash": "deepseek-chat",
                            "base_url": "https://api.deepseek.com/v1"})
    public = llm_client.save_config({"provider": "deepseek", "clear_key": True})
    assert public["has_key"] is False
    assert llm_client.load_config()["api_key"] == ""


def test_invalid_base_url_is_rejected(config_file) -> None:
    with pytest.raises(ValueError):
        llm_client.save_config({"provider": "deepseek", "base_url": "ftp://nope"})
    with pytest.raises(ValueError):
        llm_client.save_config({"provider": "deepseek", "protocol": "smoke-signals"})
    # missing models fall back to the provider preset instead of failing
    public = llm_client.save_config({"provider": "deepseek", "model": "", "model_flash": ""})
    assert public["model"] == "deepseek-v4-pro"


def test_saved_file_is_private(config_file) -> None:
    llm_client.save_config({"provider": "deepseek", "api_key": "sk-x-1234",
                            "model": "deepseek-chat", "model_flash": "deepseek-chat",
                            "base_url": "https://api.deepseek.com/v1"})
    mode = config_file.stat().st_mode & 0o777
    assert mode == 0o600


def test_merge_for_test_uses_unsaved_values(config_file) -> None:
    llm_client.save_config({"provider": "deepseek", "api_key": "sk-stored-1111",
                            "model": "deepseek-chat", "model_flash": "deepseek-chat",
                            "base_url": "https://api.deepseek.com/v1"})
    merged = llm_client.merge_for_test({
        "provider": "openai_compatible",
        "base_url": "http://127.0.0.1:9999/v1",
        "api_key": "sk-typed-2222",
        "model": "mock-model",
        "model_flash": "mock-model",
    })
    assert merged["provider"] == "openai_compatible"
    assert merged["base_url"] == "http://127.0.0.1:9999/v1"
    assert merged["api_key"] == "sk-typed-2222"
    assert merged["protocol"] == "openai"

    # masked/blank key in the test body must not leak into the runtime config
    merged_masked = llm_client.merge_for_test({"api_key": "••••••••1111"})
    assert merged_masked["api_key"] == "sk-stored-1111"


def test_provider_catalog_has_presets_and_model_lists() -> None:
    catalog = {item["id"]: item for item in llm_client.provider_catalog()}
    assert catalog["deepseek"]["model"] == "deepseek-v4-pro"
    assert catalog["anthropic"]["protocol"] == "anthropic"
    assert all(item["base_url"].startswith(("http://", "https://")) for item in catalog.values())
    for provider_id, spec in catalog.items():
        assert spec["models"], f"{provider_id} has no model list"
        ids = [model["id"] for model in spec["models"]]
        assert spec["model"] in ids or provider_id == "openai_compatible"
        assert all(model["label"] for model in spec["models"]), provider_id
        assert spec["thinking_mode"] in ("toggle", "glm-effort", "none")


def test_glm_uses_coding_plan_openai_endpoint() -> None:
    glm = {item["id"]: item for item in llm_client.provider_catalog()}["glm_coding"]
    assert glm["base_url"] == "https://api.z.ai/api/coding/paas/v4"
    assert glm["protocol"] == "openai"
    assert glm["auth_mode"] == "api_key"
    assert [m["id"] for m in glm["models"]] == ["glm-5.3", "glm-5.3-flash"]
    assert glm["thinking_mode"] == "glm-effort"


def test_glm_chain_uses_glm_effort_policy(monkeypatch, config_file) -> None:
    monkeypatch.setenv("CKA_GLM_API_KEY", "test-key")
    cfg = llm_client.load_config()
    cfg.update({"provider": "glm_coding", "api_key": "test-key",
                "model": "glm-5.3", "model_flash": "glm-5.3-flash",
                "base_url": "https://api.z.ai/api/coding/paas/v4",
                "protocol": "openai", "timeout_s": 120})
    chain = llm_client.build_chain(cfg)
    primary = chain[0]
    assert primary.id == "glm_coding"
    assert primary.thinking_mode == "glm-effort"
    assert primary.base_url.endswith("/coding/paas/v4")
