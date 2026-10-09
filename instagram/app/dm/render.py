from app.messaging import send_carousel, send_quick_replies, send_text
from app.models import QuoteSummary, RecognitionResult

HELP = (
    "Share an Instagram reel with me and I will find the product for you.\n"
    "Type 'settings' to set your spending rules: per-order and monthly limits, "
    "orders per day, an extra check for big orders, or pause buying."
)


async def results(igsid: str, result: RecognitionResult) -> None:
    if result.match_type == "none" or not result.candidates:
        await send_text(
            igsid,
            "I couldn't find this in our stores. Try sending a clearer reel "
            "or tell me what you're after.",
        )
        return
    intro = (
        "Found it! Here's where you can get it:"
        if result.match_type == "exact"
        else "Couldn't find that exact one, here are close matches:"
    )
    await send_text(igsid, intro if not result.note else f"{intro}\n{result.note}")
    await send_carousel(igsid, result)


async def quote(igsid: str, q: QuoteSummary) -> None:
    summary = (
        f"Subtotal {q.currency} {q.items_subtotal:.2f}, shipping {q.shipping:.2f}, "
        f"tax {q.tax:.2f}. Total {q.currency} {q.final_amount:.2f}."
    )
    if not q.within_budget:
        await send_text(igsid, f"{summary}\n{q.budget_message}")
        return
    await send_quick_replies(
        igsid, summary, [("Confirm", f"CONFIRM:{q.quote_id}"), ("Cancel", "CANCEL")]
    )
