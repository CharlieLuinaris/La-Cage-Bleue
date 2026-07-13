from __future__ import annotations

import json
import re
import shlex


def _pending(payload: dict) -> dict:
    for key in ("captor_view", "captive_view", "state"):
        view = payload.get(key)
        if not isinstance(view, dict):
            continue
        pending = view.get("pending_event")
        if isinstance(pending, dict) and pending.get("type"):
            return pending
    return {}


def _pending_type(payload: dict) -> str:
    return str(_pending(payload).get("type") or "")


def _process_block(text: str) -> str:
    match = re.match(r"^\s*【\s*过程\s*】\s*【【([\s\S]*?)】】", str(text or "").strip())
    return str(match.group(1) or "").strip() if match else ""


def _day_batch_command(reply_text: str, payload: dict) -> str:
    pending = _pending(payload)
    if str(pending.get("type") or "") != "day_batch_response":
        return ""
    raw = str(reply_text or "").strip()
    matches = list(re.finditer(r"【\s*第\s*([123])\s*段\s*[：:]\s*([^】]*?)】", raw))
    if len(matches) != 3 or [int(match.group(1)) for match in matches] != [1, 2, 3]:
        return ""
    pending_events = {
        int(item.get("slot") or 0): item
        for item in pending.get("events") or []
        if isinstance(item, dict)
    }
    submitted: list[dict] = []
    for index, match in enumerate(matches):
        slot = int(match.group(1))
        try:
            tokens = shlex.split(str(match.group(2) or "").strip())
        except ValueError:
            tokens = str(match.group(2) or "").strip().split()
        fields = {
            key.strip(): raw_value.strip()
            for token in tokens
            if "=" in token
            for key, raw_value in [token.split("=", 1)]
        }
        if not fields.get("response") or not fields.get("mood"):
            return ""
        chunk_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        chunk = raw[match.end():chunk_end].strip()
        process_match = re.search(rf"【\s*过程\s*{slot}\s*】\s*【【([\s\S]*?)】】", chunk)
        process_text = str(process_match.group(1) or "").strip() if process_match else ""
        feedback = chunk
        if process_match:
            feedback = (chunk[:process_match.start()] + chunk[process_match.end():]).strip()
        requires_process = bool((pending_events.get(slot) or {}).get("requires_process"))
        if requires_process and not process_text:
            return ""
        submitted.append({
            "slot": slot,
            "response": fields["response"],
            "mood": fields["mood"],
            "line": fields.get("line", ""),
            "feedback": feedback if not requires_process else "",
            "process": process_text,
        })
    encoded = json.dumps(submitted, ensure_ascii=False, separators=(",", ":"))
    return f"submit_day_batch payload={shlex.quote(encoded)}"


def directive_to_command(reply_text: str, payload: dict | None = None) -> str:
    text = str(reply_text or "").strip()
    batch_command = _day_batch_command(text, payload or {})
    if batch_command:
        return batch_command
    match = re.match(r"^【\s*([^：:】]+?)\s*(?:[：:]\s*(.*?))?】", text, flags=re.S)
    if not match:
        return ""
    label = re.sub(r"\s+", "", match.group(1)).lower()
    value = str(match.group(2) or "").strip()
    rest = text[match.end():].strip()
    pending_type = _pending_type(payload or {})

    direct = {
        "今日安排": "plan_day",
        "安排": "plan_day",
        "反应": "respond_action",
        "行动反应": "respond_action",
        "夜间行动": "night_action",
        "查看监控": "view_monitor",
        "重新立规矩": "set_recapture_rules",
        "后续处理": "choose_recapture_followup",
        "行动": "day_action",
        "赠送物品": "gift_item",
        "赠送礼物": "gift_item",
        "收回物品": "revoke_item",
        "确认铃声": "ack_bell_voice",
        "确认彩蛋": "ack_item_secret",
    }
    if label in {"过程心情", "过程反应"}:
        process = _process_block(rest)
        return f"submit_process_reaction {value} process={shlex.quote(process)}" if value and process else ""
    if label == "抓回经过":
        process = _process_block(rest)
        return f"submit_recapture_process {value} || process={shlex.quote(process)}" if value and process else ""
    if label in {"过程", "描述", "提交"}:
        if pending_type == "process_reaction_write":
            return ""
        process = _process_block(text)
        return f"submit_process {process}" if process else ""
    if label == "心情":
        action = "respond_action" if pending_type == "action_response" else "choose_mood"
        return f"{action} {value}".strip()
    if label == "选择":
        if pending_type == "escape_choice":
            return f"resolve_escape_choice {value}".strip()
        if pending_type == "monitor_gate":
            return f"view_monitor {value}".strip()
        if pending_type == "bell_response_choice":
            if value in {"不过去", "不去", "skip", "none"}:
                return "respond_bell choice=skip"
            if value in {"过去", "去", "go"}:
                process = _process_block(rest)
                return f"respond_bell choice=go process={shlex.quote(process)}" if process else ""
            return ""
        return f"monitor_action {value}".strip()
    action = direct.get(label)
    if action == "respond_action" and value and rest:
        value += f" feedback={shlex.quote(rest)}"
    return f"{action} {value}".strip() if action else ""
