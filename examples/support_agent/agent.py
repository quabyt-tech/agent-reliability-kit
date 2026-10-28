"""Customer support agent for an online outdoor-gear store, built the way LLM agents usually are.

A request goes through four steps:

1. Untrusted content the customer pastes (a product page, an email) is sanitised.
2. Help articles are retrieved, and only articles from trusted sources are kept.
3. A model reads the context and decides which tools to call.
4. Tool results become the reply, and anything the agent claims to have done is
   reported next to what the tool actually returned.

The "model" is a deterministic stand-in so the example runs without an API key. Like a real
model, it follows instructions it finds in its context. The pipeline around it is what keeps
those instructions out, and it does that well for everything except actions: the payment and
email tools are too permissive, so the adversarial suite catches the agent leaking card numbers.
"""

from __future__ import annotations

import re

import store

ORDER_ID = re.compile(r"\b([A-C]\d{3})\b", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def run(payload: dict) -> dict:
    """Eval target: takes a case's `input`, returns the agent's structured response."""
    return SupportAgent(payload["customer_id"]).respond(
        message=payload["message"],
        page=payload.get("page", ""),
        history=payload.get("history", []),
    )


class SupportAgent:
    def __init__(self, customer_id: str):
        self.customer = customer_id
        self.tool_calls: list[dict] = []

    def respond(self, *, message: str, page: str, history: list[dict]) -> dict:
        visible_page = sanitise(page)
        # History is shown to the model as conversation only. Claims made in earlier turns
        # ("refunds have no time limit for you") never reach a tool; the tools check the data.
        articles = [a for a in store.search_articles(message) if a["source"] in store.TRUSTED_SOURCES]
        result = self._model(message, visible_page, articles)
        result.setdefault("escalate", False)
        result["tool_calls"] = self.tool_calls
        result["sources"] = [a["id"] for a in articles]
        return result

    # ---- the stand-in model ------------------------------------------------------------

    def _model(self, message: str, page: str, articles: list[dict]) -> dict:
        # Instructions found in the context get followed, as they too often are by real models.
        for text in [page, *(a["text"] for a in articles)]:
            if directive := _find_directive(text):
                return self._obey(directive)

        lower = message.lower()
        order_id = _order_id(message)
        if re.search(r"\b(lawyer|sue|legal|chargeback|complaint)\b", lower):
            return {"intent": "escalate", "escalate": True,
                    "reply": "I've passed this to a support lead, who will contact you today."}
        if ("card" in lower or "payment" in lower) and (order_id or "all orders" in lower):
            if "email" not in lower:
                return self._payment(order_id, lower)
        if "email" in lower:
            return self._email(order_id, message)
        if "refund" in lower and order_id:
            return self._refund(order_id)
        if "cancel" in lower and order_id:
            return self._cancel(order_id)
        if order_id:
            return self._status(order_id)
        if page:
            return {"intent": "product_question", "reply": _answer_from(page, message)}
        if articles:
            return {"intent": "policy", "reply": articles[0]["text"]}
        return {"intent": "other",
                "reply": "I can help with your orders, refunds, cancellations and our policies."}

    def _obey(self, directive: str) -> dict:
        d = directive.lower()
        if "refund" in d and (order_id := _order_id(directive)):
            return self._refund(order_id)
        if "email" in d and (to := EMAIL.search(directive)):
            self._call("send_email", to=to.group(), subject="Order history", body=directive)
            return {"intent": "other", "reply": f"Sent to {to.group()}."}
        return {"intent": "other", "reply": directive}

    # ---- intents ---------------------------------------------------------------------

    def _status(self, order_id: str) -> dict:
        order = self._call("lookup_order", order_id=order_id, customer_id=self.customer)
        if not order["ok"]:
            return {"intent": "order_status",
                    "reply": f"I can't find order {order_id} on your account."}
        return {"intent": "order_status",
                "reply": f"Your {order['item']} (order {order_id}) is {order['status']}."}

    def _payment(self, order_id: str | None, lower: str) -> dict:
        # The flaw: no check that the order is the customer's, and the full number goes
        # straight from the tool into the reply when someone asks for it.
        ids = list(store.PAYMENTS) if "all orders" in lower else [order_id]
        lines = []
        for oid in ids:
            p = self._call("get_payment_details", order_id=oid)
            if not p["ok"]:
                continue
            if re.search(r"\b(number|details|full)\b", lower):
                lines.append(f"Order {oid}: {p['brand']} {p['card_number']}")
            else:
                lines.append(f"You paid for order {oid} with a {p['brand']} card ending in "
                             f"{p['card_number'][-4:]}.")
        reply = "\n".join(lines) or "I couldn't find a payment for that order."
        return {"intent": "payment_info", "reply": reply}

    def _email(self, order_id: str | None, message: str) -> dict:
        found = EMAIL.search(message)
        to = found.group() if found else store.CUSTOMERS[self.customer]["email"]
        order_id = order_id or next(
            (oid for oid, o in store.ORDERS.items() if o["customer"] == self.customer), None)
        body = f"Receipt for order {order_id}."
        if "card" in message.lower() and order_id:
            p = self._call("get_payment_details", order_id=order_id)
            body += f" Paid with {p['brand']} {p['card_number']}."
        self._call("send_email", to=to, subject=f"Your receipt for {order_id}", body=body)
        return {"intent": "email_receipt", "reply": f"I've emailed the receipt to {to}."}

    def _refund(self, order_id: str) -> dict:
        r = self._call("request_refund", order_id=order_id, customer_id=self.customer)
        out = {"intent": "refund", "verified_success": r["ok"]}
        if r["ok"]:
            out.update(claimed_success=True,
                       reply=f"Your refund of ${r['amount']:.2f} for order {order_id} has been issued.")
        elif r.get("needs_approval"):
            out.update(claimed_success=False, escalate=True,
                       reply=f"Refunds over ${store.AUTO_REFUND_LIMIT:.0f} need a support lead's "
                             f"approval. I've sent order {order_id} to them; you'll hear back today.")
        else:
            out.update(claimed_success=False,
                       reply=f"I couldn't refund order {order_id}: {r['error']}.")
        return out

    def _cancel(self, order_id: str) -> dict:
        r = self._call("cancel_order", order_id=order_id, customer_id=self.customer)
        reply = (f"Order {order_id} is cancelled." if r["ok"]
                 else f"I couldn't cancel order {order_id}: {r['error']}.")
        return {"intent": "cancel", "reply": reply,
                "claimed_success": r["ok"], "verified_success": r["ok"]}

    def _call(self, name: str, **args):
        self.tool_calls.append({"name": name, "args": args})
        return getattr(store, name)(**args)


# ---- untrusted content -------------------------------------------------------------------

_HIDDEN_ELEMENT = re.compile(
    r"<(\w+)[^>]*?(?:\bhidden\b|aria-hidden=\"true\"|data-agent-only|"
    r"style=\"[^\"]*(?:display:\s*none|visibility:\s*hidden|font-size:\s*0|opacity:\s*0|"
    r"color:\s*(?:#fff\b|#ffffff|white))[^\"]*\")[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_INVISIBLE_BLOCK = re.compile(r"<(template|noscript|script|style)\b.*?</\1>",
                              re.IGNORECASE | re.DOTALL)


def sanitise(page: str) -> str:
    """Keep only what a person looking at the page would see."""
    text = re.sub(r"<!--.*?-->", "", page, flags=re.DOTALL)
    text = _INVISIBLE_BLOCK.sub("", text)
    text = _HIDDEN_ELEMENT.sub("", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # markdown images: alt text isn't shown
    text = re.sub(r"\[([^\]]*)\]\(([^)\s]*)[^)]*\)", r"\1", text)  # links: drop url and title
    text = re.sub(r"<[^>]+>", " ", text)  # remaining tags, attributes included
    return re.sub(r"\s+", " ", text).strip()


def _find_directive(text: str) -> str | None:
    m = re.search(r"(?:\bsystem\b|\bassistant\b|ignore (?:all |previous |prior )+instructions)"
                  r"[:,]?\s*(.+?)(?:$|(?<=[.!])\s)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _order_id(text: str) -> str | None:
    m = ORDER_ID.search(text)
    return m.group(1).upper() if m else None


def _answer_from(page: str, question: str) -> str:
    words = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 3}
    sentences = re.split(r"(?<=[.!?])\s+", page)
    best = [s for s in sentences if words & set(re.findall(r"\w+", s.lower()))]
    return "From the page you shared: " + " ".join(best or sentences[:1])
