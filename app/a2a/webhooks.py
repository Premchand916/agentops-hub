# app/a2a/webhooks.py

import asyncio
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class WebhookSubscription:
    subscription_id: str
    task_id: str
    url: str
    secret: str | None = None


# ── Dispatcher ────────────────────────────────────────────────────────────────

class WebhookDispatcher:
    def __init__(self):
        self._subscriptions: dict[str, list[WebhookSubscription]] = {}

    def register(self, task_id: str, url: str, secret: str | None = None) -> str:
        sub_id = str(uuid.uuid4())
        sub = WebhookSubscription(
            subscription_id=sub_id,
            task_id=task_id,
            url=url,
            secret=secret,
        )
        self._subscriptions.setdefault(task_id, []).append(sub)
        return sub_id

    def unregister(self, task_id: str, subscription_id: str) -> bool:
        subs = self._subscriptions.get(task_id, [])
        new_subs = [s for s in subs if s.subscription_id != subscription_id]
        removed = len(new_subs) < len(subs)
        self._subscriptions[task_id] = new_subs
        return removed

    async def notify(self, task_id: str, event: dict[str, Any]) -> None:
        subs = list(self._subscriptions.get(task_id, []))
        if not subs:
            return
        payload = json.dumps(event).encode()
        async with httpx.AsyncClient(timeout=5.0) as client:
            await asyncio.gather(
                *(_post_with_retry(client, sub, payload) for sub in subs),
                return_exceptions=True,
            )


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _post_with_retry(
    client: httpx.AsyncClient,
    sub: WebhookSubscription,
    payload: bytes,
    max_attempts: int = 3,
) -> None:
    headers = {"Content-Type": "application/json"}
    if sub.secret:
        headers["X-A2A-Signature"] = _sign(payload, sub.secret)

    for attempt in range(max_attempts):
        try:
            r = await client.post(sub.url, content=payload, headers=headers)
            r.raise_for_status()
            return
        except Exception:
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(2 ** attempt)


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ── Public API ────────────────────────────────────────────────────────────────

def verify_signature(payload: bytes, secret: str, signature: str) -> bool:
    """Verify an HMAC-SHA256 webhook signature. Use this on the receiver side."""
    expected = _sign(payload, secret)
    return hmac.compare_digest(expected, signature)


# ── Singleton ─────────────────────────────────────────────────────────────────

webhook_dispatcher = WebhookDispatcher()
