"""LLMClient — multi-provider adapter (Anthropic + OpenAI-compatible + Ollama), with fallback."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app import config

GLM_MODEL = "glm-5.3"
GLM_MODEL_FLASH = "glm-5.3-flash"

CATALOG: dict[str, dict[str, object]] = {
    "glm_coding": {
        "protocol": "openai",
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "auth_mode": "api_key",
        "model": "glm-5.3",
        "model_flash": "glm-5.3-flash",
        "models": [
            {"id": "glm-5.3", "label": "GLM-5.3 (flagship coding)"},
            {"id": "glm-5.3-flash", "label": "GLM-5.3-Flash (fast, multimodal)"},
        ],
        "thinking_mode": "glm-effort",
    },
    "deepseek": {
        "protocol": "openai",
        "base_url": "https://api.deepseek.com",
        "auth_mode": "api_key",
        "model": "deepseek-v4-pro",
        "model_flash": "deepseek-flash",
        "models": [
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
            {"id": "deepseek-flash", "label": "DeepSeek Flash (V4.1)"},
            {"id": "deepseek-chat", "label": "deepseek-chat (legacy alias)"},
        ],
        "thinking_mode": "toggle",
    },
    "opencode_go": {
        "protocol": "openai",
        "base_url": "https://opencode.ai/zen/go/v1",
        "auth_mode": "api_key",
        "model": "deepseek-v4-pro",
        "model_flash": "glm-5.3-flash",
        "models": [
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
            {"id": "deepseek-v4.1-flash", "label": "DeepSeek V4.1 Flash"},
            {"id": "glm-5.3", "label": "GLM-5.3"},
            {"id": "glm-5.3-flash", "label": "GLM-5.3-Flash"},
            {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
            {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5"},
            {"id": "gpt-5.6", "label": "GPT-5.6"},
            {"id": "gpt-6", "label": "GPT-6"},
        ],
        "thinking_mode": "toggle",
    },
    "anthropic": {
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "auth_mode": "api_key",
        "model": "claude-opus-5-5",
        "model_flash": "claude-haiku-5-5",
        "models": [
            {"id": "claude-fable-5-2", "label": "Claude Fable 5.2 (deep reasoning)"},
            {"id": "claude-opus-5-5", "label": "Claude Opus 5.5 (agentic coding)"},
            {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5 (balanced)"},
            {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5 (fast)"},
        ],
        "thinking_mode": "none",
    },
    "openai_compatible": {
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "auth_mode": "api_key",
        "model": "gpt-6.2-sol",
        "model_flash": "gpt-6-luna",
        "models": [
            {"id": "gpt-6.2-sol", "label": "GPT-6.2 Sol"},
            {"id": "gpt-6.2-astra", "label": "GPT-6.2 Astra"},
            {"id": "gpt-6.1-terra", "label": "GPT-6.1 Terra"},
            {"id": "gpt-6-luna", "label": "GPT-6 Luna"},
            {"id": "gpt-5.1", "label": "GPT-5.1"},
            {"id": "gpt-4.1", "label": "GPT-4.1"},
            {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"},
        ],
        "thinking_mode": "toggle",
    },
    "ollama": {
        "protocol": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "auth_mode": "none",
        "model": "qwen2.5-coder:14b",
        "model_flash": "qwen2.5-coder:7b",
        "models": [
            {"id": "qwen2.5-coder:14b", "label": "Qwen 2.5 Coder 14B (local)"},
            {"id": "qwen2.5-coder:7b", "label": "Qwen 2.5 Coder 7B (fast local)"},
            {"id": "qwen3:14b", "label": "Qwen 3 14B (local)"},
        ],
        "thinking_mode": "none",
    },
}

ENV_KEYS: dict[str, tuple[str, ...]] = {
    "glm_coding": ("CKA_GLM_API_KEY", "GLM_API_KEY", "ZAI_API_KEY"),
    "deepseek": ("CKA_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    "opencode_go": ("CKA_OPENCODE_API_KEY", "OPENCODE_API_KEY"),
    "anthropic": ("CKA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    "openai_compatible": ("CKA_OPENAI_API_KEY", "OPENAI_API_KEY"),
}


class LLMError(RuntimeError):
    pass


@dataclass
class Provider:
    id: str
    protocol: str
    base_url: str
    auth_mode: str
    api_key: str
    model: str
    model_flash: str
    timeout_s: float
    reasoning_effort: str | None = None
    thinking_disabled: bool = False
    thinking_mode: str = "toggle"   # toggle | glm-effort | none


def _env_key(provider_id: str) -> str | None:
    for name in ENV_KEYS.get(provider_id, ()):
        value = os.environ.get(name)
        if value:
            return value
    return None


def config_path() -> Path:
    return config.LLM_CONFIG_PATH


def resolve_config_path() -> Path | None:
    path = config_path()
    return path if path.exists() else None


def _mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 4:
        return "••••"
    return "••••••••" + key[-4:]


def provider_catalog() -> list[dict[str, Any]]:
    """Public provider catalog (UI)."""
    return [
        {
            "id": provider_id,
            "protocol": spec["protocol"],
            "base_url": spec["base_url"],
            "model": spec["model"],
            "model_flash": spec["model_flash"],
            "auth_mode": spec["auth_mode"],
            "models": spec.get("models", []),
            "thinking_mode": spec.get("thinking_mode", "toggle"),
        }
        for provider_id, spec in CATALOG.items()
    ]


def _read_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text())
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def load_config() -> dict[str, Any]:
    """Priority: ./llm_config.json (or CKA_LLM_CONFIG) then CKA_LLM_* env vars."""
    raw: dict[str, Any] = {}
    path = resolve_config_path()
    if path:
        raw = _read_file(path)
    provider_id = str(raw.get("provider") or "deepseek")
    preset = CATALOG.get(provider_id, {})
    auth_mode = str(raw.get("auth_mode") or preset.get("auth_mode", "api_key"))
    cfg: dict[str, Any] = {
        "provider": provider_id,
        "protocol": raw.get("protocol") or preset.get("protocol", "openai"),
        "base_url": raw.get("base_url") or preset.get("base_url", ""),
        "auth_mode": auth_mode,
        "api_key": raw.get("api_key") or "",
        "model": raw.get("model") or preset.get("model", ""),
        "model_flash": raw.get("model_flash") or raw.get("model") or preset.get("model_flash", ""),
        "timeout_s": float(raw.get("timeout_s") or 120),
        "reasoning_effort": raw.get("reasoning_effort"),
        "thinking": raw.get(
            "thinking",
            os.environ.get("CKA_LLM_THINKING", "off" if provider_id == "deepseek" else "on"),
        ),
    }
    overrides = {
        "provider": os.environ.get("CKA_LLM_PROVIDER"),
        "base_url": os.environ.get("CKA_LLM_BASE_URL"),
        "api_key": os.environ.get("CKA_LLM_API_KEY"),
        "model": os.environ.get("CKA_LLM_MODEL"),
        "model_flash": os.environ.get("CKA_LLM_MODEL_FLASH"),
        "reasoning_effort": os.environ.get("CKA_LLM_REASONING_EFFORT"),
    }
    for key, value in overrides.items():
        if value:
            cfg[key] = value
    if cfg["provider"] in CATALOG and not cfg["model"]:
        cfg["model"] = CATALOG[cfg["provider"]]["model"]
        cfg["model_flash"] = CATALOG[cfg["provider"]]["model_flash"]
    if cfg["provider"] == "deepseek":
        cfg["timeout_s"] = max(float(cfg["timeout_s"]), 300.0)
    if cfg["auth_mode"] == "none":
        cfg["_source"] = "local"
    elif raw.get("api_key"):
        cfg["_source"] = "file"
    elif os.environ.get("CKA_LLM_API_KEY"):
        cfg["_source"] = "env"
    else:
        cfg["_source"] = "unconfigured"
    return cfg


def public_config() -> dict[str, Any]:
    """Safe view for the frontend — the raw API key never leaves the server."""
    cfg = load_config()
    key = str(cfg.get("api_key") or "")
    has_auth = bool(key) or cfg.get("auth_mode") == "none"
    return {
        "provider": cfg["provider"],
        "protocol": cfg["protocol"],
        "base_url": cfg["base_url"],
        "auth_mode": cfg["auth_mode"],
        "model": cfg["model"],
        "model_flash": cfg["model_flash"],
        "timeout_s": cfg["timeout_s"],
        "thinking": cfg.get("thinking", "on"),
        "reasoning_effort": cfg.get("reasoning_effort"),
        "has_key": has_auth,
        "api_key_masked": _mask_key(key),
        "source": cfg.get("_source", "unconfigured"),
        "providers": provider_catalog(),
    }


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist provider config, preserving the stored key when the UI sends a masked value."""
    path = config_path()
    current = load_config()
    provider_id = str(payload.get("provider") or current["provider"]).strip()
    preset = CATALOG.get(provider_id, CATALOG["deepseek"])

    protocol = str(payload.get("protocol") or preset["protocol"]).strip().lower()
    if protocol not in ("anthropic", "openai"):
        raise ValueError(f"invalid protocol: {protocol}")

    base_url = str(payload.get("base_url") or preset["base_url"]).strip()
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")

    model = str(payload.get("model") or preset["model"]).strip()
    model_flash = str(payload.get("model_flash") or preset["model_flash"]).strip()
    if not model or not model_flash:
        raise ValueError("model and model_flash are required")

    auth_mode = str(payload.get("auth_mode") or preset["auth_mode"]).strip()
    if auth_mode not in ("api_key", "auth_token", "none"):
        auth_mode = "api_key"

    raw_key = payload.get("api_key")
    if payload.get("clear_key"):
        final_key = ""
    elif raw_key is None or str(raw_key).strip() == "" or str(raw_key).strip().startswith("••"):
        final_key = str(current.get("api_key") or "") if current.get("_source") == "file" else ""
    else:
        final_key = str(raw_key).strip()

    thinking = str(payload.get("thinking") or current.get("thinking") or ("off" if provider_id == "deepseek" else "on")).strip().lower()
    if thinking not in ("on", "off"):
        thinking = "off" if provider_id == "deepseek" else "on"

    timeout_s = float(payload.get("timeout_s") or current.get("timeout_s") or 120)
    stored: dict[str, Any] = {
        "provider": provider_id,
        "protocol": protocol,
        "base_url": base_url,
        "auth_mode": auth_mode,
        "api_key": final_key,
        "model": model,
        "model_flash": model_flash,
        "timeout_s": max(5.0, min(600.0, timeout_s)),
        "thinking": thinking,
    }
    reasoning_effort = payload.get("reasoning_effort", current.get("reasoning_effort"))
    if reasoning_effort:
        stored["reasoning_effort"] = str(reasoning_effort).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, indent=2, ensure_ascii=False))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return public_config()


def merge_for_test(override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Effective config for a test call: stored config + unsaved UI overrides."""
    cfg = load_config()
    if not override:
        return cfg
    merged = dict(cfg)
    for key in ("provider", "protocol", "base_url", "auth_mode", "model",
                "model_flash", "timeout_s", "thinking", "reasoning_effort"):
        if override.get(key) not in (None, ""):
            merged[key] = override[key]
    key = override.get("api_key")
    if key and not str(key).startswith("••"):
        merged["api_key"] = str(key)
    preset = CATALOG.get(str(merged["provider"]), {})
    merged["protocol"] = merged.get("protocol") or preset.get("protocol", "openai")
    merged["timeout_s"] = float(merged.get("timeout_s") or 120)
    return merged


async def test_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """One cheap provider round-trip with the given config (used by the UI test button)."""
    started = time.monotonic()
    client = LLMClient(cfg=cfg)
    try:
        text, meta = await client.complete(
            [{"role": "user", "content": "Reply with exactly OK"}],
            role="flash", max_tokens=20,
        )
    finally:
        await client.aclose()
    return {
        "ok": True,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "reply": text.strip()[:40],
    }


def build_chain(cfg: dict[str, Any]) -> list[Provider]:
    """Primary configured provider + catalog providers with env keys."""
    primary = Provider(
        id=str(cfg["provider"]),
        protocol=str(cfg["protocol"]),
        base_url=str(cfg["base_url"]),
        auth_mode=str(cfg["auth_mode"]),
        api_key=str(cfg["api_key"]),
        model=str(cfg["model"]),
        model_flash=str(cfg["model_flash"]),
        timeout_s=float(cfg["timeout_s"]),
        reasoning_effort=cfg.get("reasoning_effort") or ("low" if cfg["provider"] == "deepseek" else None),
        thinking_disabled=cfg.get("thinking") == "off",
        thinking_mode=str(CATALOG.get(str(cfg["provider"]), {}).get("thinking_mode", "toggle")),
    )
    chain = [primary]
    for provider_id, spec in CATALOG.items():
        if provider_id == primary.id:
            continue
        key = _env_key(provider_id)
        if not key:
            continue
        chain.append(
            Provider(
                id=provider_id,
                protocol=spec["protocol"],
                base_url=spec["base_url"],
                auth_mode=spec["auth_mode"],
                api_key=key,
                model=spec["model"],
                model_flash=spec["model_flash"],
                timeout_s=float(cfg["timeout_s"]),
                reasoning_effort=("low" if provider_id == "deepseek" else None),
                thinking_disabled=(os.environ.get("CKA_LLM_THINKING", "off") == "off"
                                   and provider_id == "deepseek"),
                thinking_mode=str(spec.get("thinking_mode", "toggle")),
            )
        )
    return chain


class LLMClient:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or load_config()
        self.chain = build_chain(self.cfg)
        self._http: httpx.AsyncClient | None = None
        self._http_loop: asyncio.AbstractEventLoop | None = None

    def reload_config(self) -> None:
        """Re-read ./llm_config.json after the UI saves a new provider config."""
        self.cfg = load_config()
        self.chain = build_chain(self.cfg)

    def is_configured(self) -> bool:
        return any(bool(p.api_key) or p.auth_mode == "none" for p in self.chain)

    async def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._http is None or self._http.is_closed or self._http_loop is not loop:
            if self._http is not None and not self._http.is_closed:
                try:
                    await self._http.aclose()
                except Exception:
                    pass
            self._http = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8)
            )
            self._http_loop = loop
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            try:
                await self._http.aclose()
            except Exception:
                pass
        self._http = None
        self._http_loop = None

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        role: str = "main",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        json_mode: bool = False,
        deep: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        errors: list[str] = []
        for provider in self.chain:
            model = provider.model_flash if role == "flash" else provider.model
            started = time.perf_counter()
            try:
                text, usage = await self._call(
                    provider, model, messages, temperature, max_tokens, json_mode, deep
                )
                duration_ms = round((time.perf_counter() - started) * 1000)
                meta: dict[str, Any] = {
                    "provider": provider.id,
                    "model": model,
                    "duration_ms": duration_ms,
                    **usage,
                }
                return text, meta
            except Exception as exc:
                errors.append(f"{provider.id}: {type(exc).__name__}: {str(exc)[:160]}")
                continue
        raise LLMError("all providers failed — " + " | ".join(errors))

    async def _call(
        self,
        provider: Provider,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        deep: bool,
    ) -> tuple[str, dict[str, Any]]:
        if not provider.api_key and provider.auth_mode != "none":
            raise LLMError(f"{provider.id}: missing api_key")
        headers: dict[str, str] = {"content-type": "application/json"}
        if provider.protocol == "anthropic":
            if provider.auth_mode == "auth_token":
                headers["authorization"] = f"Bearer {provider.api_key}"
            else:
                headers["x-api-key"] = provider.api_key
            headers["anthropic-version"] = "2023-06-01"
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            body: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [m for m in messages if m["role"] != "system"],
            }
            if system:
                body["system"] = system
            url = provider.base_url.rstrip("/") + "/v1/messages"
        else:
            if provider.api_key:
                headers["authorization"] = f"Bearer {provider.api_key}"
            elif provider.auth_mode == "none":
                headers["authorization"] = "Bearer ollama"
            url = provider.base_url.rstrip("/") + "/chat/completions"
            body = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode and provider.id != "ollama":
                body["response_format"] = {"type": "json_object"}
            if provider.reasoning_effort:
                body["reasoning_effort"] = provider.reasoning_effort
            if provider.thinking_mode == "glm-effort":
                body["thinking"] = {"type": "enabled"}
                body["reasoning_effort"] = "max" if deep else "low"
            elif provider.thinking_mode == "none":
                pass
            elif provider.thinking_disabled and not deep:
                body["thinking"] = {"type": "disabled"}

        client = await self._client()
        response = await client.post(url, headers=headers, json=body, timeout=provider.timeout_s)
        if response.status_code >= 400:
            raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        raw_usage = data.get("usage") or {}
        if provider.protocol == "anthropic":
            blocks = data.get("content") or []
            text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
            usage = {
                "prompt_tokens": raw_usage.get("input_tokens"),
                "completion_tokens": raw_usage.get("output_tokens"),
                "reasoning_tokens": None,
            }
            return text, usage
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("response without choices")
        choice = choices[0]
        message = choice.get("message", {}) or {}
        content = message.get("content") or ""
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]
        if choice.get("finish_reason") == "length":
            raise LLMError("truncated response (finish_reason=length) — increase max_tokens")
        details = raw_usage.get("completion_tokens_details") or {}
        usage = {
            "prompt_tokens": raw_usage.get("prompt_tokens"),
            "completion_tokens": raw_usage.get("completion_tokens"),
            "reasoning_tokens": details.get("reasoning_tokens"),
        }
        return content, usage
