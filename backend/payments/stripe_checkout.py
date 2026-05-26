import json
import logging
from pathlib import Path
from typing import Optional

import stripe

from backend.storage.database import (
    create_payment,
    get_payment_by_job,
    get_payment_by_session,
    get_job,
    update_job_payment_status,
    update_payment,
)

_logger = logging.getLogger("payments")

PRICING_PATH = Path(__file__).resolve().parent.parent / "config" / "pricing.json"


def _load_pricing() -> dict:
    try:
        return json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        _logger.warning("Failed to load pricing.json: %s; using defaults", e)
        return {"unit_amount_usd": 9.00, "currency": "usd", "product_name": "Lead Export"}


def configure_stripe(api_key: str) -> None:
    stripe.api_key = api_key


def create_checkout_session(
    job_id: int,
    success_url: str,
    cancel_url: str,
) -> Optional[str]:
    pricing = _load_pricing()
    unit_amount_cents = int(round(pricing["unit_amount_usd"] * 100))
    currency = pricing.get("currency", "usd")
    product_name = pricing.get("product_name", "Lead Export")

    job = get_job(job_id)
    if not job:
        _logger.warning("Checkout requested for nonexistent job %d", job_id)
        return None

    existing = get_payment_by_job(job_id)
    if existing and existing["status"] == "completed":
        _logger.info("Job %d already paid — returning existing session", job_id)
        return existing.get("stripe_session_id") or None

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "unit_amount": unit_amount_cents,
                        "currency": currency,
                        "product_data": {
                            "name": f"{product_name} — Job #{job_id}",
                            "description": f"{job.get('source', 'unknown')}: {job.get('query', '')[:80] or ''}",
                        },
                    },
                    "quantity": 1,
                }
            ],
            metadata={"job_id": str(job_id), "source": job.get("source", "")},
            success_url=success_url,
            cancel_url=cancel_url,
        )

        create_payment(
            scrape_job_id=job_id,
            amount=pricing["unit_amount_usd"],
            currency=currency,
            stripe_session_id=session.id,
        )

        _logger.info(
            "Checkout session %s created for job %d (amount=$%.2f %s)",
            session.id, job_id, pricing["unit_amount_usd"], currency.upper(),
        )
        return session.url

    except stripe.error.StripeError as e:
        _logger.error("Stripe checkout session creation failed for job %d: %s", job_id, e)
        return None


def handle_webhook_event(payload: bytes, sig_header: str, endpoint_secret: str) -> Optional[str]:
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        _logger.warning("Webhook signature verification failed: %s", e)
        return None

    event_type = event.get("type", "")
    _logger.info("Processing Stripe webhook event: %s (id=%s)", event_type, event.get("id", ""))

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session.get("id", "")
        payment_status = session.get("payment_status", "")

        if payment_status != "paid":
            _logger.info("Session %s payment_status is '%s' — skipping", session_id, payment_status)
            return session_id

        existing = get_payment_by_session(session_id)
        if not existing:
            _logger.warning("No payment record for session %s", session_id)
            return session_id

        if existing["status"] == "completed":
            _logger.info("Session %s already processed — idempotency skip", session_id)
            return session_id

        job_id = existing["scrape_job_id"]
        update_payment(existing["id"], status="completed", stripe_session_id=session_id)
        update_job_payment_status(job_id, "paid")
        _logger.info("Payment completed for session %s → job %d unlocked", session_id, job_id)

    return event.get("id") if event_type == "checkout.session.completed" else event.get("id")


def get_payment_status(job_id: int) -> dict:
    job = get_job(job_id)
    if not job:
        return {"paid": False, "exists": False}
    payment = get_payment_by_job(job_id)
    return {
        "paid": job.get("payment_status", "unpaid") == "paid",
        "exists": payment is not None,
        "payment_status": payment["status"] if payment else None,
    }
