# Nova Notify — Push Webhook Service

## Overview
Nova Notify delivers real-time events via **push webhooks**. When an event occurs, the server POSTs a JSON payload to your configured callback URL. You do not need to poll for changes.

## Authentication
All API requests require a **Bearer token** in the `Authorization` header:

```
Authorization: Bearer <your_token>
```

Tokens are generated from the Nova dashboard under Settings > API Keys.

## Webhook Registration

### Register a webhook endpoint
Register your callback URL so Nova can push events to you.

- **Method:** POST
- **Endpoint:** `https://api.novanotify.io/v1/webhooks/register`
- **Body:**
  ```json
  {
    "callback_url": "https://your-server.com/notify",
    "events": ["stock.change"]
  }
  ```

### Response on success (201)
```json
{
  "webhook_id": "wh_abc123",
  "status": "active"
}
```

## Event Payload Format
When Nova pushes an event, the POST body contains:

```json
{
  "event_type": "stock.change",
  "timestamp": 1700000000,
  "data": {
    "product_id": "SKU-1001",
    "old_stock": 50,
    "new_stock": 48
  }
}
```

## Rate Limits
- Up to 100 webhooks per account.
- Events delivered at least once; idempotency key: `event_id`.
