import re
from typing import Optional

from app import state
from app.config import settings


def set_budget(user_id: str, per_order: float, currency: str) -> None:
    state.update_user(user_id, budget_per_order=per_order, budget_currency=currency)


def clear_budget(user_id: str) -> None:
    state.update_user(user_id, budget_per_order=None, budget_currency=None)


def get_budget(user_id: str) -> tuple[float, str] | None:
    u = state.get_user(user_id)
    if u.get("budget_per_order") is None:
        return None
    return u["budget_per_order"], u.get("budget_currency") or settings.reap_default_currency


def check_budget(user_id: str, final_amount: float, currency: str) -> tuple[bool, Optional[str]]:
    """Returns (within_budget, message_if_over)."""
    b = get_budget(user_id)
    if b is None or final_amount <= b[0]:
        return True, None
    limit, cur = b
    return False, (
        f"That comes to {currency} {final_amount:.2f} with shipping and tax, which is over "
        f"your limit of {cur} {limit:.2f}. Want to raise your budget or pick something cheaper?"
    )


def handle_budget_command(user_id: str, text: str) -> Optional[str]:
    """Handles 'budget', 'budget 150', 'budget off'. Returns reply text, or None if not a budget command."""
    m = re.fullmatch(r"\s*budget(?:\s+(\S+))?\s*", text, flags=re.I)
    if not m:
        return None
    arg = m.group(1)
    cur = settings.reap_default_currency
    if arg is None:
        b = get_budget(user_id)
        return (
            f"Your per-order limit is {b[1]} {b[0]:.2f}."
            if b
            else "No budget set. Send 'budget 150' to set a per-order limit."
        )
    if arg.lower() == "off":
        clear_budget(user_id)
        return "Budget limit removed."
    try:
        amount = float(arg)
    except ValueError:
        return "Send a number, for example 'budget 150'."
    if amount <= 0:
        return "The budget must be more than zero."
    set_budget(user_id, amount, cur)
    return f"Done. I will not buy anything over {cur} {amount:.2f} per order."
