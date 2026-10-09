"""Interactive 'Spending rules' menu: taps for presets, or type a custom number."""
import re
from typing import Optional

from app import state
from app.meta.send import send_quick_replies, send_text
from app.purchase import policy
from app.purchase.policy import RULES

MENU_WORDS = {"settings", "rules", "limits", "menu", "spending", "spending rules"}


async def open_menu(uid: str) -> None:
    state.update_user(uid, awaiting=None)
    paused = policy.is_paused(uid)
    options = [(r.title, f"SET:{r.key}") for r in RULES.values()]
    options.append(("Resume buying" if paused else "Pause buying", "SET:pause"))
    options.append(("Done", "SET:done"))
    await send_quick_replies(uid, "Your spending rules:\n" + policy.summary(uid) + "\n\nWhat do you want to change?", options)


async def open_rule(uid: str, key: str) -> None:
    rule = RULES[key]
    state.update_user(uid, awaiting=key)
    options = [(policy.fmt(rule, p), f"SETVAL:{key}:{p}") for p in rule.presets]
    options += [("No limit", f"SETVAL:{key}:off"), ("Back", "SET:menu")]
    now = policy.fmt(rule, policy.get(uid, key))
    await send_quick_replies(
        uid, f"{rule.question}.\nCurrently: {now}.\nTap a choice, or type your own number.", options
    )


def parse_value(text: str) -> Optional[float]:
    m = re.fullmatch(r"\s*(?:sgd|\$)?\s*(\d+(?:\.\d+)?)\s*", text.lower())
    return float(m.group(1)) if m and float(m.group(1)) > 0 else None


async def apply(uid: str, key: str, value: Optional[float]) -> None:
    rule = RULES[key]
    policy.set_rule(uid, key, value)
    state.update_user(uid, awaiting=None)
    msg = f"{rule.title} removed." if value is None else f"{rule.title} set to {policy.fmt(rule, value)}."
    await send_text(uid, msg)
    await open_menu(uid)


async def handle_tap(uid: str, payload: str) -> bool:
    """SET:<key>, SETVAL:<key>:<value>. Returns True if the payload was a settings one."""
    kind, _, rest = payload.partition(":")
    if kind == "SET":
        if rest in ("menu", ""):
            await open_menu(uid)
        elif rest == "pause":
            policy.set_paused(uid, not policy.is_paused(uid))
            await send_text(uid, "Buying is paused." if policy.is_paused(uid) else "Buying is back on.")
            await open_menu(uid)
        elif rest == "done":
            state.update_user(uid, awaiting=None)
            await send_text(uid, "Saved. Share a reel any time.\n" + policy.summary(uid))
        elif rest in RULES:
            await open_rule(uid, rest)
        return True
    if kind == "SETVAL":
        key, _, val = rest.partition(":")
        if key in RULES:
            await apply(uid, key, None if val == "off" else float(val))
        return True
    return False


async def handle_text(uid: str, text: str) -> bool:
    """Handles the menu words and a typed number while a rule is open. True if handled."""
    t = text.strip().lower()
    if t in MENU_WORDS:
        await open_menu(uid)
        return True
    key = state.get_user(uid).get("awaiting")
    if not key:
        return False
    if t in ("off", "none", "no limit"):
        await apply(uid, key, None)
        return True
    value = parse_value(t)
    if value is None:
        await send_text(uid, "Please send a number like 150, or tap a choice. Type 'menu' to go back.")
        return True
    await apply(uid, key, value)
    return True
