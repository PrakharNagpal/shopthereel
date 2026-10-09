"""Spending rules: what each rule is, how it is stored, and how a quote is checked against them."""
from dataclasses import dataclass
from typing import Optional

from app import state
from app.config import settings


@dataclass(frozen=True)
class Rule:
    key: str            # used in SET:<key> payloads
    column: str         # users table column
    title: str          # shown on the menu button (max 20 chars)
    question: str
    presets: tuple      # quick-reply choices
    is_money: bool = True


RULES = {
    r.key: r
    for r in (
        Rule("per_order", "budget_per_order", "Per-order limit",
             "The most I may spend on a single order", (50, 100, 200, 500)),
        Rule("monthly", "budget_monthly", "Monthly limit",
             "The most I may spend in a calendar month", (200, 500, 1000, 2000)),
        Rule("daily", "max_orders_per_day", "Orders per day",
             "How many orders I may place in a day", (1, 2, 3, 5), is_money=False),
        Rule("confirm", "confirm_above", "Extra check",
             "Orders above this amount need a second confirmation", (50, 100, 200)),
    )
}


def get(user_id: str, key: str) -> Optional[float]:
    return state.get_user(user_id).get(RULES[key].column)


def set_rule(user_id: str, key: str, value: Optional[float]) -> None:
    rule = RULES[key]
    fields = {rule.column: value}
    if key == "per_order":
        fields["budget_currency"] = settings.reap_default_currency if value is not None else None
    if key == "daily" and value is not None:
        fields[rule.column] = int(value)
    state.update_user(user_id, **fields)


def is_paused(user_id: str) -> bool:
    return bool(state.get_user(user_id).get("buying_paused"))


def set_paused(user_id: str, paused: bool) -> None:
    state.update_user(user_id, buying_paused=1 if paused else 0)


def fmt(rule: Rule, value: Optional[float]) -> str:
    if value is None:
        return "off"
    return f"{settings.reap_default_currency} {value:g}" if rule.is_money else f"{int(value)}"


def summary(user_id: str) -> str:
    lines = [f"{r.title}: {fmt(r, get(user_id, r.key))}" for r in RULES.values()]
    m = get(user_id, "monthly")
    if m is not None:
        lines.append(
            f"Spent this month: {settings.reap_default_currency} {state.month_spent(user_id):.2f}"
        )
    lines.append("Buying: PAUSED" if is_paused(user_id) else "Buying: on")
    return "\n".join(lines)


def check_quote(user_id: str, final_amount: float, currency: str) -> tuple[bool, Optional[str]]:
    """Returns (allowed, refusal_message). Run on every quote, before a Confirm button is shown."""
    if is_paused(user_id):
        return False, "Buying is paused. Open 'settings' and tap Resume buying to continue."
    per_order = get(user_id, "per_order")
    if per_order is not None and final_amount > per_order:
        return False, (
            f"That comes to {currency} {final_amount:.2f} with shipping and tax, which is over "
            f"your limit of {currency} {per_order:g}. Want to raise your budget or pick something cheaper?"
        )
    monthly = get(user_id, "monthly")
    if monthly is not None:
        spent = state.month_spent(user_id)
        if spent + final_amount > monthly:
            left = max(monthly - spent, 0)
            return False, (
                f"That comes to {currency} {final_amount:.2f}, but your monthly limit of "
                f"{currency} {monthly:g} only has {currency} {left:.2f} left. "
                "Open 'settings' to change it."
            )
    daily = get(user_id, "daily")
    if daily is not None and state.orders_today(user_id) >= int(daily):
        return False, f"You have reached your limit of {int(daily)} order(s) today. Try again tomorrow, or open 'settings'."
    return True, None


def needs_extra_confirm(user_id: str, final_amount: float) -> bool:
    above = get(user_id, "confirm")
    return above is not None and final_amount > above
