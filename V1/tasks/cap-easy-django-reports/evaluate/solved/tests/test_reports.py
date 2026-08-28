from __future__ import annotations

import csv
import io
import os
from pathlib import Path

os.environ.setdefault("REPORTS_DB", str(Path.cwd() / "test-reports.sqlite3"))

import manage
from django.db import connection
from django.test import Client


_ADMIN_HEADERS = {"HTTP_X_REPORT_TOKEN": "reports-admin"}


def setup_function() -> None:
    manage.reset_database()


def test_ingests_events_and_returns_grouped_summary_with_filters_and_pagination():
    client = Client()

    created = client.post(
        "/events",
        data={"event_type": "sale", "occurred_on": "2024-05-01", "category": "books", "amount": 1200},
        content_type="application/json",
    )
    client.post(
        "/events",
        data={"event_type": "refund", "occurred_on": "2024-05-01", "category": "books", "amount": 200},
        content_type="application/json",
    )
    client.post(
        "/events",
        data={"event_type": "sale", "occurred_on": "2024-05-02", "category": "games", "amount": 900},
        content_type="application/json",
    )
    client.post(
        "/events",
        data={"event_type": "sale", "occurred_on": "2024-05-03", "category": "books", "amount": 500},
        content_type="application/json",
    )

    summary = client.get(
        "/reports/summary?start_date=2024-05-01&end_date=2024-05-03&category=books&page=1&page_size=5",
        **_ADMIN_HEADERS,
    )
    payload = summary.json()

    assert created.status_code == 201
    assert created.json()["event_type"] == "sale"
    assert summary.status_code == 200
    assert payload["page"] == 1
    assert payload["page_size"] == 5
    assert payload["total"] == 2
    assert payload["items"][0]["date"] == "2024-05-03"
    assert payload["items"][0]["net_total"] == 500
    assert payload["items"][1]["date"] == "2024-05-01"
    assert payload["items"][1]["sales_total"] == 1200
    assert payload["items"][1]["refund_total"] == 200
    assert payload["items"][1]["net_total"] == 1000
    assert payload["items"][1]["event_count"] == 2


def test_exports_csv_and_tracks_report_history():
    client = Client()
    for event in [
        {"event_type": "sale", "occurred_on": "2024-05-01", "category": "books", "amount": 1200},
        {"event_type": "refund", "occurred_on": "2024-05-01", "category": "books", "amount": 200},
        {"event_type": "sale", "occurred_on": "2024-05-02", "category": "games", "amount": 900},
    ]:
        response = client.post("/events", data=event, content_type="application/json")
        assert response.status_code == 201

    csv_response = client.get("/reports/summary?format=csv&page=1&page_size=10", **_ADMIN_HEADERS)
    json_response = client.get("/reports/summary?page=1&page_size=10", **_ADMIN_HEADERS)
    history = client.get("/reports/history?page=1&page_size=10", **_ADMIN_HEADERS)

    rows = list(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8"))))
    history_payload = history.json()

    assert csv_response.status_code == 200
    assert csv_response["Content-Type"].startswith("text/csv")
    assert rows[0]["date"] == "2024-05-02"
    assert rows[0]["category"] == "games"
    assert rows[1]["category"] == "books"
    assert rows[1]["sales_total"] == "1200"
    assert rows[1]["refund_total"] == "200"
    assert json_response.status_code == 200
    assert history.status_code == 200
    assert history_payload["total"] == 2
    assert history_payload["items"][0]["format"] == "json"
    assert history_payload["items"][1]["format"] == "csv"
    assert history_payload["items"][0]["returned_rows"] == 2


def test_validation_and_permissions():
    client = Client()

    invalid_event = client.post(
        "/events",
        data={"event_type": "oops", "occurred_on": "bad-date", "category": "", "amount": -1},
        content_type="application/json",
    )
    unauthorized = client.get("/reports/summary")
    invalid_page = client.get("/reports/summary?page=0", **_ADMIN_HEADERS)
    invalid_format = client.get("/reports/summary?format=xml", **_ADMIN_HEADERS)
    invalid_range = client.get(
        "/reports/summary?start_date=2024-05-04&end_date=2024-05-01",
        **_ADMIN_HEADERS,
    )
    history = client.get("/reports/history?page=1&page_size=10", **_ADMIN_HEADERS)

    assert invalid_event.status_code == 400
    assert "errors" in invalid_event.json()
    assert unauthorized.status_code == 401
    assert invalid_page.status_code == 400
    assert invalid_format.status_code == 400
    assert invalid_range.status_code == 400
    assert history.json()["total"] == 0


def test_schema_is_created_automatically_on_first_endpoint_use():
    db_path = Path(os.environ["REPORTS_DB"])
    connection.close()
    if db_path.exists():
        db_path.unlink()

    client = Client()
    created = client.post(
        "/events",
        data={"event_type": "sale", "occurred_on": "2024-05-01", "category": "books", "amount": 1200},
        content_type="application/json",
    )
    summary = client.get("/reports/summary?page=1&page_size=10", **_ADMIN_HEADERS)

    assert created.status_code == 201
    assert summary.status_code == 200
    assert summary.json()["total"] == 1
    assert db_path.exists()
