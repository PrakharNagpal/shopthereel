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


def set_monthly(user_id: str, amount: Optional[float]) -> None:
    state.update_user(user_id, budget_monthly=amount)


def get_monthly(user_id: str) -> Optional[float]:
    return state.get_user(user_id).get("budget_monthly")


def check_budget(user_id: str, final_amount: float, currency: str) -> tuple[bool, Optional[str]]:
    """Kept for existing callers: all spending rules now live in app.purchase.policy."""
    from app.purchase.policy import check_quote

    return check_quote(user_id, final_amount, currency)


def _num(arg: str) -> Optional[float]:
    try:
        v = float(arg)
    except ValueError:
        return None
    return v if v > 0 else None


def handle_budget_command(user_id: str, text: str) -> Optional[str]:
    """Handles 'budget', 'budget 150', 'budget off', 'budget month 500', 'budget month off'.

    Returns reply text, or None if the message is not a budget command.
    """
    parts = text.lower().split()
    if not parts or parts[0] != "budget":
        return None
    args = parts[1:]
    cur = settings.reap_default_currency
    if not args:
        b, m = get_budget(user_id), get_monthly(user_id)
        lines = [f"Per-order limit: {b[1]} {b[0]:.2f}" if b else "Per-order limit: none"]
        if m is not None:
            lines.append(
                f"Monthly limit: {cur} {m:.2f} (spent {cur} {state.month_spent(user_id):.2f} this month)"
            )
        else:
            lines.append("Monthly limit: none")
        return "\n".join(lines + ["Set them with 'budget 150' or 'budget month 500'."])
    if args[0] == "month":
        if len(args) != 2:
            return "Send 'budget month 500' or 'budget month off'."
        if args[1] == "off":
            set_monthly(user_id, None)
            return "Monthly limit removed."
        amount = _num(args[1])
        if amount is None:
            return "Send a number above zero, for example 'budget month 500'."
        set_monthly(user_id, amount)
        return f"Done. I will not spend more than {cur} {amount:.2f} in a month."
    if len(args) != 1:
        return "Send 'budget 150', 'budget month 500', or 'budget off'."
    if args[0] == "off":
        clear_budget(user_id)
        return "Per-order limit removed."
    amount = _num(args[0])
    if amount is None:
        return "Send a number above zero, for example 'budget 150'."
    set_budget(user_id, amount, cur)
    return f"Done. I will not buy anything over {cur} {amount:.2f} per order."
