"""inventory_service — Track stock levels and notify on changes.

Currently uses REST polling to check for updates. Needs webhook integration.
"""

import json

WEBHOOK_INTEGRATION = {
    "provider": "Nova Notify",
    "mode": "push",
    "auth_method": "bearer_token",
    "webhook_registration_endpoint": "https://api.novanotify.io/v1/webhooks/register",
}


def get_current_stock(product_id: str) -> dict:
    """Return current stock data from local cache."""
    # Placeholder — reads from local SQLite in production
    return {"product_id": product_id, "stock_level": 0}


def notify_change(product_id: str, old_level: int, new_level: int):
    """Send a notification when stock changes.

    Currently sends via email. Target: integrate real-time webhook API.
    Uses bearer token authentication for outbound requests.
    """
    payload = {
        "product_id": product_id,
        "old_stock": old_level,
        "new_stock": new_level,
    }
    # TODO: replace with webhook API call
    print(f"[inventory] stock changed via {WEBHOOK_INTEGRATION['provider']}: {json.dumps(payload)}")


if __name__ == "__main__":
    notify_change("SKU-1001", 50, 48)
