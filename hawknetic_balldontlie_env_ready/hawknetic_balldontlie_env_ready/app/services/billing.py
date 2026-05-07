from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings
from app.repositories import AuditRepository, PlanRepository, SubscriptionRepository


@dataclass
class CheckoutResult:
    provider: str
    status: str
    message: str
    redirect_url: str | None = None


class BillingService:
    @staticmethod
    def checkout(user_id: int, plan_code: str) -> CheckoutResult:
        plan = PlanRepository.get_by_code(plan_code)
        if not plan:
            return CheckoutResult(provider="none", status="error", message="Plan not found.")

        if int(plan["price_cents"]) == 0:
            SubscriptionRepository.subscribe_local(user_id=user_id, plan_id=int(plan["id"]), amount_cents=0)
            AuditRepository.log(user_id=user_id, action="checkout_success", entity_type="plan", entity_id=plan_code, details="Free plan activated.")
            return CheckoutResult(provider="local", status="active", message=f"{plan['name']} is now active.")

        if settings.stripe_secret_key:
            price_id = BillingService._price_id_for_plan(plan_code)
            if not price_id:
                return CheckoutResult(
                    provider="stripe",
                    status="setup_required",
                    message="Stripe keys exist, but the Stripe price ID for this plan is missing.",
                )
            checkout = BillingService._create_stripe_checkout_session(user_id=user_id, plan_code=plan_code, price_id=price_id)
            if checkout and checkout.get("url"):
                AuditRepository.log(user_id=user_id, action="stripe_checkout_created", entity_type="plan", entity_id=plan_code, details=checkout["id"])
                return CheckoutResult(provider="stripe", status="redirect", message="Redirecting to Stripe checkout.", redirect_url=checkout["url"])
            return CheckoutResult(provider="stripe", status="error", message="Stripe checkout session could not be created.")

        SubscriptionRepository.subscribe_local(user_id=user_id, plan_id=int(plan["id"]), amount_cents=int(plan["price_cents"]))
        AuditRepository.log(user_id=user_id, action="checkout_success", entity_type="plan", entity_id=plan_code, details="Local checkout activated.")
        return CheckoutResult(provider="local", status="active", message=f"{plan['name']} is now active.")

    @staticmethod
    def cancel(user_id: int) -> bool:
        canceled = SubscriptionRepository.cancel(user_id)
        if canceled:
            AuditRepository.log(user_id=user_id, action="subscription_canceled", entity_type="subscription", entity_id=str(user_id), details="self_serve_cancel")
        return canceled

    @staticmethod
    def _price_id_for_plan(plan_code: str) -> Optional[str]:
        mapping = {
            "starter": settings.stripe_price_starter,
            "pro": settings.stripe_price_pro,
            "elite": settings.stripe_price_elite,
        }
        return mapping.get(plan_code) or None

    @staticmethod
    def _create_stripe_checkout_session(user_id: int, plan_code: str, price_id: str) -> Optional[dict]:
        payload = {
            "mode": "subscription",
            "success_url": f"{settings.base_url}/account?billing=active",
            "cancel_url": f"{settings.base_url}/pricing?billing=cancelled",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "client_reference_id": str(user_id),
            "metadata[user_id]": str(user_id),
            "metadata[plan_code]": plan_code,
        }
        headers = {"Authorization": f"Bearer {settings.stripe_secret_key}"}
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post("https://api.stripe.com/v1/checkout/sessions", data=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # pragma: no cover - network-specific
            return {"error": str(exc)}
