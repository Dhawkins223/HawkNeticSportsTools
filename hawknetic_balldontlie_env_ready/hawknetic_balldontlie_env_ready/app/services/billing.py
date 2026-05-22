"""HawkneticSports billing service — Stripe Checkout + Portal + Webhook.

Endpoints exposed by routes/api.py:
  POST /api/billing/create-checkout-session   — create Stripe Checkout for Pro/Premium
  POST /api/billing/create-portal-session     — create Stripe Customer Portal session
  GET  /api/billing/subscription              — return current plan + status from DB
  POST /api/webhooks/stripe                   — verified webhook (signature checked)

Implementation rules (from playbook):
  - Plan price IDs come from server env vars (STRIPE_PRICE_ID_PRO, STRIPE_PRICE_ID_PREMIUM).
  - Frontend supplies origin URL only — backend constructs success/cancel URLs.
  - Every checkout creates a `payment_transactions` row BEFORE redirecting.
  - Webhook signature is verified using STRIPE_WEBHOOK_SECRET; bad signatures → 400.
  - Webhook events update `users.plan`, `users.subscription_status`, `subscriptions`, `payments`.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import stripe
from fastapi import HTTPException

from app.database import execute, get_connection

PLANS = {
    "pro": {"env_key": "STRIPE_PRICE_ID_PRO", "max_slip_runs": 50, "label": "Pro"},
    "premium": {"env_key": "STRIPE_PRICE_ID_PREMIUM", "max_slip_runs": 250, "label": "Premium"},
}

PLAN_RUN_LIMITS = {"free": 3, "pro": 50, "premium": 250}


def _stripe_key() -> str:
    key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Stripe is not configured.")
    return key


def _webhook_secret() -> str:
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret not configured.")
    return secret


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_checkout_session(*, user_id: int, user_email: str, plan: str, origin: str) -> dict[str, Any]:
    if plan not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan. Choose 'pro' or 'premium'.")
    price_id = os.environ.get(PLANS[plan]["env_key"])
    if not price_id or "placeholder" in price_id:
        raise HTTPException(status_code=503, detail=f"{PLANS[plan]['label']} price ID is not configured. Set {PLANS[plan]['env_key']} in the backend .env.")

    stripe.api_key = _stripe_key()
    success_url = f"{origin.rstrip('/')}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin.rstrip('/')}/pricing"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=user_email,
            client_reference_id=str(user_id),
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": str(user_id), "plan": plan},
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe rejected the checkout request: {getattr(exc, 'user_message', None) or str(exc)}") from exc

    with get_connection() as conn:
        execute(conn, """
            INSERT INTO payment_transactions(user_id, user_email, session_id, amount, currency, plan_name, payment_status, metadata, created_at, updated_at)
            VALUES(?, ?, ?, NULL, 'usd', ?, 'pending', ?, ?, ?)
        """, (user_id, user_email, session.id, plan, json.dumps({"plan": plan}), _now_iso(), _now_iso()))

    return {"ok": True, "session_id": session.id, "url": session.url}


def create_portal_session(*, user_id: int, origin: str) -> dict[str, Any]:
    stripe.api_key = _stripe_key()
    with get_connection() as conn:
        row = execute(conn, "SELECT stripe_customer_id FROM users WHERE id = ?", (user_id,)).fetchone()
    customer_id = dict(row).get("stripe_customer_id") if row else None
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found. Subscribe to a plan first.")
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{origin.rstrip('/')}/dashboard",
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(status_code=502, detail=f"Stripe rejected the portal request: {getattr(exc, 'user_message', None) or str(exc)}") from exc
    return {"ok": True, "url": session.url}


def get_subscription_for_user(user_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        user = execute(conn, "SELECT plan, subscription_status, stripe_customer_id, stripe_subscription_id FROM users WHERE id = ?", (user_id,)).fetchone()
        sub = execute(conn, "SELECT plan_name, status, current_period_start, current_period_end, cancel_at_period_end FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    plan = (dict(user).get("plan") if user else None) or "free"
    return {
        "plan": plan,
        "subscription_status": dict(user).get("subscription_status") if user else None,
        "stripe_customer_id": dict(user).get("stripe_customer_id") if user else None,
        "stripe_subscription_id": dict(user).get("stripe_subscription_id") if user else None,
        "limits": {"daily_slip_runs": PLAN_RUN_LIMITS.get(plan, 3)},
        "current": dict(sub) if sub else None,
    }


def handle_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    """Verify Stripe signature, then dispatch on event type."""
    secret = _webhook_secret()
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Stripe signature: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}") from exc

    event_type = event["type"]
    data = event["data"]["object"]

    handlers = {
        "checkout.session.completed": _handle_checkout_completed,
        "customer.subscription.created": _handle_subscription_upsert,
        "customer.subscription.updated": _handle_subscription_upsert,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.payment_succeeded": _handle_payment_succeeded,
        "invoice.payment_failed": _handle_payment_failed,
    }
    handler = handlers.get(event_type)
    if handler is None:
        return {"ok": True, "event": event_type, "ignored": True}
    handler(data)
    return {"ok": True, "event": event_type}


def _user_id_from_event(data: dict[str, Any]) -> int | None:
    metadata = data.get("metadata") or {}
    if metadata.get("user_id"):
        try:
            return int(metadata["user_id"])
        except ValueError:
            return None
    if data.get("client_reference_id"):
        try:
            return int(data["client_reference_id"])
        except ValueError:
            return None
    customer = data.get("customer")
    if customer:
        with get_connection() as conn:
            row = execute(conn, "SELECT id FROM users WHERE stripe_customer_id = ?", (customer,)).fetchone()
        if row:
            return int(dict(row).get("id"))
    return None


def _handle_checkout_completed(data: dict[str, Any]) -> None:
    user_id = _user_id_from_event(data)
    plan = (data.get("metadata") or {}).get("plan", "pro")
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")
    if not user_id:
        return
    with get_connection() as conn:
        execute(conn, """
            UPDATE users SET plan = ?, subscription_status = 'active', stripe_customer_id = ?, stripe_subscription_id = ?, updated_at = ?
            WHERE id = ?
        """, (plan, customer_id, subscription_id, _now_iso(), user_id))
        execute(conn, """
            UPDATE payment_transactions SET payment_status = 'completed', stripe_subscription_id = ?, updated_at = ? WHERE session_id = ?
        """, (subscription_id, _now_iso(), data.get("id")))


def _handle_subscription_upsert(data: dict[str, Any]) -> None:
    user_id = _user_id_from_event(data)
    if not user_id:
        return
    plan = _plan_from_subscription(data)
    status = data.get("status")
    period_start = _ts_to_iso(data.get("current_period_start"))
    period_end = _ts_to_iso(data.get("current_period_end"))
    cancel_at_period_end = 1 if data.get("cancel_at_period_end") else 0
    with get_connection() as conn:
        execute(conn, """
            UPDATE users SET plan = ?, subscription_status = ?, stripe_subscription_id = ?, updated_at = ?
            WHERE id = ?
        """, (plan or "free", status, data.get("id"), _now_iso(), user_id))
        existing = execute(conn, "SELECT id FROM subscriptions WHERE stripe_subscription_id = ?", (data.get("id"),)).fetchone()
        if existing:
            execute(conn, """
                UPDATE subscriptions SET plan_name = ?, status = ?, current_period_start = ?, current_period_end = ?, cancel_at_period_end = ?, updated_at = ?
                WHERE stripe_subscription_id = ?
            """, (plan or "free", status, period_start, period_end, cancel_at_period_end, _now_iso(), data.get("id")))
        else:
            execute(conn, """
                INSERT INTO subscriptions(user_id, stripe_customer_id, stripe_subscription_id, plan_name, status, current_period_start, current_period_end, cancel_at_period_end, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (user_id, data.get("customer"), data.get("id"), plan or "free", status, period_start, period_end, cancel_at_period_end, _now_iso(), _now_iso()))


def _handle_subscription_deleted(data: dict[str, Any]) -> None:
    user_id = _user_id_from_event(data)
    if not user_id:
        return
    with get_connection() as conn:
        execute(conn, "UPDATE users SET plan = 'free', subscription_status = 'canceled', updated_at = ? WHERE id = ?", (_now_iso(), user_id))
        execute(conn, "UPDATE subscriptions SET status = 'canceled', updated_at = ? WHERE stripe_subscription_id = ?", (_now_iso(), data.get("id")))


def _handle_payment_succeeded(data: dict[str, Any]) -> None:
    user_id = _user_id_from_event(data)
    if not user_id:
        return
    amount_cents = data.get("amount_paid") or data.get("amount_due") or 0
    with get_connection() as conn:
        execute(conn, """
            INSERT INTO payments(user_id, stripe_invoice_id, amount, currency, status, paid_at, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
        """, (user_id, data.get("id"), amount_cents / 100.0, data.get("currency", "usd"), "paid", _ts_to_iso(data.get("status_transitions", {}).get("paid_at") or data.get("created")), _now_iso()))


def _handle_payment_failed(data: dict[str, Any]) -> None:
    user_id = _user_id_from_event(data)
    if not user_id:
        return
    with get_connection() as conn:
        execute(conn, "UPDATE users SET subscription_status = 'past_due', updated_at = ? WHERE id = ?", (_now_iso(), user_id))


def _plan_from_subscription(data: dict[str, Any]) -> str | None:
    items = ((data.get("items") or {}).get("data") or [])
    if not items:
        return None
    price_id = items[0].get("price", {}).get("id")
    if not price_id:
        return None
    if price_id == os.environ.get("STRIPE_PRICE_ID_PRO"):
        return "pro"
    if price_id == os.environ.get("STRIPE_PRICE_ID_PREMIUM"):
        return "premium"
    return None


def _ts_to_iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
