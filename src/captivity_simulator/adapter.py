from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

from .configuration import render_placeholders
from .reference import get_reference, reference_tool_schema


class AdapterError(RuntimeError):
    pass


GAME_CHANNEL_LABEL = "（囚禁模拟器频道）"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"


def _request_chat_completion(body: dict[str, Any], *, base_url: str, api_key: str, timeout: int) -> dict[str, Any]:
    req = request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AdapterError(f"AI request failed: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _anthropic_reference_tool() -> dict[str, Any]:
    function = reference_tool_schema()["function"]
    return {
        "name": function["name"],
        "description": function["description"],
        "input_schema": function["parameters"],
    }


def _request_anthropic_message(body: dict[str, Any], *, base_url: str, api_key: str, timeout: int) -> dict[str, Any]:
    req = request.Request(
        f"{base_url}/v1/messages",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AdapterError(f"AI request failed: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _request_assistant_anthropic(prompt: str, ai: dict[str, Any], channel_message: str) -> str:
    base_url = str(ai.get("base_url") or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
    model = str(ai.get("model") or "")
    env_name = str(ai.get("api_key_env") or "CAPTIVITY_AI_API_KEY")
    api_key = os.environ.get(env_name, "")
    if not model or not api_key:
        raise AdapterError("AI adapter config is incomplete.")
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": int(ai.get("max_tokens") or 4096),
        "system": prompt,
        "messages": [{"role": "user", "content": channel_message}],
        "tools": [_anthropic_reference_tool()],
    }
    timeout = int(ai.get("timeout_seconds") or 120)
    for _ in range(3):
        payload = _request_anthropic_message(body, base_url=base_url, api_key=api_key, timeout=timeout)
        content = payload.get("content")
        if not isinstance(content, list):
            raise AdapterError("AI response does not contain content blocks.")
        tool_uses = [block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"]
        if not tool_uses:
            texts = [
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "".join(texts).strip()
        body["messages"].append({"role": "assistant", "content": content})
        results: list[dict[str, Any]] = []
        for block in tool_uses:
            if str(block.get("name") or "") != "captivity_simulator_reference":
                result = json.dumps({"error": "unknown_tool"}, ensure_ascii=False)
            else:
                arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
                result = get_reference(str((arguments or {}).get("分类") or (arguments or {}).get("category") or ""))
            results.append({
                "type": "tool_result",
                "tool_use_id": str(block.get("id") or ""),
                "content": result,
            })
        body["messages"].append({"role": "user", "content": results})
    raise AdapterError("AI exceeded the reference-tool round limit.")


def request_assistant(prompt: str, config: dict[str, Any], player_message: str = "") -> str:
    ai = config.get("ai") if isinstance(config.get("ai"), dict) else {}
    if not ai.get("enabled"):
        raise AdapterError("AI adapter is disabled; copy the generated prompt into your assistant manually.")
    channel_message = (
        f"{GAME_CHANNEL_LABEL}\n{{user}}：{player_message.strip()}"
        if player_message.strip()
        else "（囚禁模拟器频道系统提示）{user}没有发文字消息给你"
    )
    rendered_message = str(render_placeholders(channel_message, config))
    provider = str(ai.get("provider") or "openai").strip().lower()
    if provider == "anthropic":
        return _request_assistant_anthropic(prompt, ai, rendered_message)
    if provider != "openai":
        raise AdapterError(f"Unknown AI provider: {provider}.")
    base_url = str(ai.get("base_url") or "").rstrip("/")
    model = str(ai.get("model") or "")
    env_name = str(ai.get("api_key_env") or "CAPTIVITY_AI_API_KEY")
    api_key = os.environ.get(env_name, "")
    if not base_url or not model or not api_key:
        raise AdapterError("AI adapter config is incomplete.")
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": prompt,
            },
            {
                "role": "user",
                "content": rendered_message,
            },
        ],
        "tools": [reference_tool_schema()],
        "tool_choice": "auto",
        "temperature": float(ai.get("temperature") or 0.9),
        "stream": False,
    }
    timeout = int(ai.get("timeout_seconds") or 120)
    for _ in range(3):
        payload = _request_chat_completion(body, base_url=base_url, api_key=api_key, timeout=timeout)
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterError("AI response does not contain choices[0].message.") from exc
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        if not isinstance(tool_calls, list) or not tool_calls:
            return str((message or {}).get("content") or "").strip()
        body["messages"].append(message)
        for tool_call in tool_calls:
            function = tool_call.get("function") if isinstance(tool_call, dict) else {}
            if str((function or {}).get("name") or "") != "captivity_simulator_reference":
                result = {"error": "unknown_tool"}
            else:
                try:
                    arguments = json.loads(str((function or {}).get("arguments") or "{}"))
                except json.JSONDecodeError:
                    arguments = {}
                result = get_reference(str((arguments or {}).get("分类") or (arguments or {}).get("category") or ""))
            body["messages"].append({
                "role": "tool",
                "tool_call_id": str(tool_call.get("id") or ""),
                "content": result,
            })
    raise AdapterError("AI exceeded the reference-tool round limit.")
