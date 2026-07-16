from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from captivity_simulator.adapter import request_assistant


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class AdapterTest(unittest.TestCase):
    def test_uses_labeled_user_envelope_and_resolves_reference_tool(self) -> None:
        requests: list[dict] = []
        responses = iter([
            {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "captivity_simulator_reference",
                                "arguments": '{"分类":"喂食"}',
                            },
                        }],
                    }
                }]
            },
            {"choices": [{"message": {"role": "assistant", "content": "【今日安排：...】"}}]},
        ])

        def fake_urlopen(req, timeout=0):
            requests.append(json.loads(req.data.decode("utf-8")))
            return _Response(next(responses))

        config = {
            "ai": {
                "enabled": True,
                "base_url": "https://example.invalid/v1",
                "api_key_env": "TEST_CAPTIVITY_KEY",
                "model": "test-model",
            }
        }
        with patch.dict("os.environ", {"TEST_CAPTIVITY_KEY": "secret"}), patch(
            "captivity_simulator.adapter.request.urlopen", side_effect=fake_urlopen
        ):
            reply = request_assistant("当前事件", config, player_message="我想说的话")

        self.assertEqual(reply, "【今日安排：...】")
        system_message, player_message = requests[0]["messages"]
        self.assertEqual(system_message, {"role": "system", "content": "当前事件"})
        self.assertEqual(player_message["role"], "user")
        self.assertEqual(player_message["content"], "（囚禁模拟器频道）\n{user}：我想说的话")
        self.assertEqual(requests[0]["tools"][0]["function"]["name"], "captivity_simulator_reference")
        self.assertEqual(requests[1]["messages"][-1]["role"], "tool")
        self.assertIn("始终包含一份正常食物", requests[1]["messages"][-1]["content"])

    def test_no_player_text_uses_explicit_channel_system_notice(self) -> None:
        captured: dict = {}

        def fake_urlopen(req, timeout=0):
            captured.update(json.loads(req.data.decode("utf-8")))
            return _Response({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

        config = {
            "actors": {"user": "Player", "assistant": "Partner"},
            "ai": {
                "enabled": True,
                "base_url": "https://example.invalid/v1",
                "api_key_env": "TEST_CAPTIVITY_KEY",
                "model": "test-model",
            },
        }
        with patch.dict("os.environ", {"TEST_CAPTIVITY_KEY": "secret"}), patch(
            "captivity_simulator.adapter.request.urlopen", side_effect=fake_urlopen
        ):
            self.assertEqual(request_assistant("当前事件", config), "ok")

        self.assertEqual(
            captured["messages"][-1]["content"],
            "（囚禁模拟器频道系统提示）Player没有发文字消息给你",
        )


class AnthropicAdapterTest(unittest.TestCase):
    def test_anthropic_provider_resolves_reference_tool(self) -> None:
        requests_seen: list[dict] = []
        urls: list[str] = []
        headers_seen: list[dict] = []
        responses = iter([
            {
                "content": [{
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "captivity_simulator_reference",
                    "input": {"分类": "喂食"},
                }],
                "stop_reason": "tool_use",
            },
            {"content": [{"type": "text", "text": "【今日安排：...】"}], "stop_reason": "end_turn"},
        ])

        def fake_urlopen(req, timeout=0):
            urls.append(req.full_url)
            headers_seen.append(dict(req.headers))
            requests_seen.append(json.loads(req.data.decode("utf-8")))
            return _Response(next(responses))

        config = {
            "ai": {
                "enabled": True,
                "provider": "anthropic",
                "api_key_env": "TEST_CAPTIVITY_KEY",
                "model": "claude-opus-4-8",
            }
        }
        with patch.dict("os.environ", {"TEST_CAPTIVITY_KEY": "secret"}), patch(
            "captivity_simulator.adapter.request.urlopen", side_effect=fake_urlopen
        ):
            reply = request_assistant("当前事件", config, player_message="我想说的话")

        self.assertEqual(reply, "【今日安排：...】")
        self.assertEqual(urls[0], "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers_seen[0].get("X-api-key"), "secret")
        self.assertEqual(headers_seen[0].get("Anthropic-version"), "2023-06-01")
        self.assertEqual(requests_seen[0]["system"], "当前事件")
        self.assertEqual(requests_seen[0]["messages"][0]["role"], "user")
        self.assertEqual(requests_seen[0]["messages"][0]["content"], "（囚禁模拟器频道）\n{user}：我想说的话")
        self.assertEqual(requests_seen[0]["tools"][0]["name"], "captivity_simulator_reference")
        self.assertNotIn("temperature", requests_seen[0])
        followup = requests_seen[1]["messages"]
        self.assertEqual(followup[1]["role"], "assistant")
        tool_turn = followup[-1]
        self.assertEqual(tool_turn["role"], "user")
        self.assertEqual(tool_turn["content"][0]["type"], "tool_result")
        self.assertEqual(tool_turn["content"][0]["tool_use_id"], "toolu-1")
        self.assertIn("始终包含一份正常食物", tool_turn["content"][0]["content"])

    def test_anthropic_provider_renders_actor_names_and_joins_text_blocks(self) -> None:
        captured: dict = {}

        def fake_urlopen(req, timeout=0):
            captured.update(json.loads(req.data.decode("utf-8")))
            return _Response({
                "content": [
                    {"type": "text", "text": "前半"},
                    {"type": "text", "text": "后半"},
                ],
                "stop_reason": "end_turn",
            })

        config = {
            "actors": {"user": "Player", "assistant": "Partner"},
            "ai": {
                "enabled": True,
                "provider": "anthropic",
                "base_url": "https://example.invalid",
                "api_key_env": "TEST_CAPTIVITY_KEY",
                "model": "claude-opus-4-8",
            },
        }
        with patch.dict("os.environ", {"TEST_CAPTIVITY_KEY": "secret"}), patch(
            "captivity_simulator.adapter.request.urlopen", side_effect=fake_urlopen
        ):
            self.assertEqual(request_assistant("当前事件", config), "前半后半")

        self.assertEqual(
            captured["messages"][0]["content"],
            "（囚禁模拟器频道系统提示）Player没有发文字消息给你",
        )

    def test_unknown_provider_is_rejected(self) -> None:
        config = {"ai": {"enabled": True, "provider": "carrier-pigeon", "model": "m"}}
        with self.assertRaises(Exception) as ctx:
            request_assistant("当前事件", config)
        self.assertIn("Unknown AI provider", str(ctx.exception))


class ClaudeCliAdapterTest(unittest.TestCase):
    def test_claude_p_provider_invokes_print_mode(self) -> None:
        captured: dict = {}

        def fake_run(command, capture_output=False, text=False, timeout=0):
            captured["command"] = command
            captured["timeout"] = timeout
            return subprocess.CompletedProcess(command, 0, stdout="【今日安排：...】\n", stderr="")

        config = {
            "actors": {"user": "Player", "assistant": "Partner"},
            "ai": {"enabled": True, "provider": "claude-p", "model": "claude-fable-5"},
        }
        with patch("captivity_simulator.adapter.subprocess.run", side_effect=fake_run):
            reply = request_assistant("当前事件", config, player_message="我想说的话")

        self.assertEqual(reply, "【今日安排：...】")
        command = captured["command"]
        self.assertEqual(command[0], "claude")
        self.assertEqual(command[1], "-p")
        self.assertEqual(command[2], "（囚禁模拟器频道）\nPlayer：我想说的话")
        system_prompt = command[command.index("--system-prompt") + 1]
        self.assertTrue(system_prompt.startswith("当前事件"))
        self.assertIn("白天行动", system_prompt)
        self.assertIn("始终包含一份正常食物", system_prompt)
        self.assertEqual(command[command.index("--model") + 1], "claude-fable-5")
        self.assertIn("--disallowedTools", command)
        self.assertEqual(captured["timeout"], 300)

    def test_claude_p_failure_surfaces_stderr(self) -> None:
        def fake_run(command, capture_output=False, text=False, timeout=0):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not logged in")

        config = {"ai": {"enabled": True, "provider": "claude-p"}}
        with patch("captivity_simulator.adapter.subprocess.run", side_effect=fake_run):
            with self.assertRaises(Exception) as ctx:
                request_assistant("当前事件", config)
        self.assertIn("not logged in", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
