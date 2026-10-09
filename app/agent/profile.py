"""Editable demo context, scoped to the configured Telegram demo chats."""
import hashlib
import json
import re
from pathlib import Path

from app.config import settings

SEED = Path(__file__).with_name("demo_profile.json")
FIELDS = {"home", "not_owned", "pantry", "likes", "dislikes", "sizes", "background"}


def load_profile(user_id: str | None) -> dict:
    allowed = {v.strip() for v in settings.telegram_allowed_chat_ids.split(",") if v.strip()}
    if not user_id or settings.front_door != "telegram" or user_id not in allowed:
        return {}
    path = _path(user_id)
    return json.loads(path.read_text() if path.exists() else SEED.read_text())


def _path(user_id: str) -> Path:
    return Path("cache/profiles") / (hashlib.sha256(user_id.encode()).hexdigest() + ".json")


def update_profile(user_id: str, field: str, value: str) -> None:
    profile = load_profile(user_id)
    if not profile or field not in FIELDS:
        raise ValueError("Unknown profile field")
    value = value.strip()[:1000]
    if field == "sizes":
        sizes = {}
        for pair in value.split(","):
            key, separator, val = pair.partition("=")
            if not separator or not key.strip() or not val.strip():
                raise ValueError("Use sizes shirt=M, shoes=EU42; these are examples only.")
            sizes[key.strip().lower()] = val.strip()
        profile[field] = sizes
    elif field == "background":
        profile[field] = value
    else:
        profile[field] = [v.strip() for v in value.split(",") if v.strip()]
        if field in ("home", "not_owned"):
            other = "not_owned" if field == "home" else "home"
            profile[other] = [v for v in profile[other] if v.lower() not in {x.lower() for x in profile[field]}]
    if field in ("pantry", "home"):
        profile.setdefault("inventory_facts", {})[field] = {item.casefold(): True for item in profile[field]}
    profile["sample_fields"] = [v for v in profile.get("sample_fields", []) if v != field]
    save_profile(user_id, profile)


def save_profile(user_id: str, profile: dict) -> None:
    path = _path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(profile, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def describe_profile(user_id: str) -> str:
    p = load_profile(user_id)
    if not p:
        return "No demo profile is configured for this chat."
    sample = set(p.get("sample_fields", []))
    lines = ["Your demo profile", p["background"]]
    for field in ("home", "not_owned", "pantry", "likes", "dislikes", "sizes"):
        value = p[field]
        text = ", ".join(f"{k}={v}" for k, v in value.items()) if isinstance(value, dict) else ", ".join(value)
        suffix = " (sample assumptions)" if field in sample else ""
        lines.append(f"{field.replace('_', ' ').title()}{suffix}: {text or 'not provided'}")
    lines += ["", "Edit with: profile set home oven, blender",
              "Other fields: not_owned, pantry, likes, dislikes, sizes, background.",
              "For sizes, use key=value pairs. No size will be selected automatically.",
              "Try: demo air fryer"]
    return "\n".join(lines)


def excluded(candidate_name: str, profile: dict) -> bool:
    """Only explicit product exclusions; broad dislikes remain advisory context."""
    name = candidate_name.casefold()
    if re.search(r"\b(tray|dish|pan|rack|liner|accessory|mitt|glove|cover|filter|recipe|cookbook)\b", name):
        return False  # owning an appliance does not mean owning its accessories
    owned = profile.get("home", [])
    return any(re.search(r"\b" + re.escape(item.casefold()) + r"\b", name) for item in owned if len(item) >= 4)
