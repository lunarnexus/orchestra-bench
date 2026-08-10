# SyncPulse — Polling Event Service

## Overview
SyncPulse delivers events via **polling**. You query the API endpoint to fetch any new events since your last request. The service does not push data to you — you pull it on a schedule.

## Authentication
All requests require an **API key** passed as a query parameter:

```
GET /events?api_key=<your_key>
```

Keys are generated from the SyncPulse console under Account > Integrations.

## Fetching Events

### Get new events (polling)
Poll this endpoint to retrieve any unprocessed events.

- **Method:** GET
- **Endpoint:** `https://events.syncpulse.com/v2/events`
- **Query params:**
  - `api_key` — your API key (required)
  - `since` — Unix timestamp; only return events after this time (optional)
  - `limit` — max events to return, default 50

### Response on success (200)
```json
{
  "events": [
    {
      "event_id": "ev_xyz789",
      "type": "stock.change",
      "timestamp": 1700000000,
      "data": {
        "product_id": "SKU-1001",
        "old_stock": 50,
        "new_stock": 48
      }
    }
  ],
  "has_more": false
}
```

## Recommended Polling Interval
Poll every **30 seconds** for near-real-time updates. Polling more frequently may result in rate limiting (max 120 requests/minute).
