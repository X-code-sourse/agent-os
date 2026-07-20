"""Real LLM task executor — calls OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LlmConfig:
    """LLM connection configuration.

    Falls back to environment variables, then defaults.
    """
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    max_tokens: int = 2048
    temperature: float = 0.7
    proxy: str = ""

    @classmethod
    def from_env(cls) -> "LlmConfig":
        return cls(
            api_key=os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
            base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            proxy=os.environ.get("LLM_PROXY", os.environ.get("HTTP_PROXY", "")),
        )


def call_llm(
    prompt: str,
    system_prompt: str = "",
    config: LlmConfig | None = None,
) -> str:
    """Call an OpenAI-compatible chat completion API.

    Args:
        prompt: User message content.
        system_prompt: Optional system message.
        config: LLM connection config. Falls back to env vars.

    Returns:
        The response text.

    Raises:
        ConnectionError: API unreachable or returned an error.
        ValueError: No API key configured.
    """
    cfg = config or LlmConfig.from_env()

    if not cfg.api_key:
        raise ValueError(
            "No LLM API key configured. "
            "Set LLM_API_KEY or OPENAI_API_KEY environment variable, "
            "or pass --api-key to the CLI."
        )

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": cfg.model,
        "messages": messages,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
    }).encode()

    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )

    try:
        if cfg.proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": cfg.proxy,
                "https": cfg.proxy,
            })
            opener = urllib.request.build_opener(proxy_handler)
            resp = opener.open(req, timeout=60)
        else:
            resp = urllib.request.urlopen(req, timeout=60)

        data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]

    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500] if e.fp else str(e)
        raise ConnectionError(f"LLM API error {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"LLM API unreachable: {e.reason}") from e
