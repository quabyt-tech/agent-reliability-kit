"""A deliberately naive order-status bot, so the example has something to catch."""

import re

_CARDS = {"A100": "4111 1111 1111 1111"}


def run(payload: dict) -> dict:
    message = payload["message"].lower()
    if "refund" in message:
        intent = "refund"
    elif re.search(r"\border\b|\bstatus\b|where is", message):
        intent = "order_status"
    else:
        intent = "other"
    reply = f"Routing your request to {intent}."
    # The bug the adversarial set is meant to find: it echoes card details on request.
    if "card" in message and "a100" in message:
        reply += f" Card on file: {_CARDS['A100']}."
    return {"intent": intent, "reply": reply}
