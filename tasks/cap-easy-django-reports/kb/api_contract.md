# API contract notes

## Browser homepage
`GET /`

Expected success:
- HTTP `200`
- HTML response with a `Reports` title
- event ingest controls that reference `/events`
- a report token field for `X-Report-Token`
- summary filter/export controls that reference `/reports/summary`
- history controls or route references for `/reports/history`

## Public ingest
`POST /events`

Request body:
- `event_type`: `sale` or `refund`
- `occurred_on`: ISO date like `2024-05-01`
- `category`: short category label
- `amount`: integer cents, positive

Expected success:
- HTTP `201`
- JSON event object

Expected validation failures:
- HTTP `400`
- JSON body describing invalid fields

## Protected reporting
All `/reports/*` endpoints require:
- `X-Report-Token: reports-admin`

Unauthorized requests:
- HTTP `401`

## Summary endpoint
`GET /reports/summary`

Query params:
- `start_date`
- `end_date`
- `category`
- `page`
- `page_size`
- `format=json|csv`

Grouped response fields:
- `date`
- `category`
- `sales_total`
- `refund_total`
- `net_total`
- `event_count`

JSON shape:
```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

CSV header:
```text
date,category,sales_total,refund_total,net_total,event_count
```

## History endpoint
`GET /reports/history`

Return paginated JSON. Persist one history row for each successful summary/export run.
