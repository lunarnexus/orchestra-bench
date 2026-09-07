from __future__ import annotations

import csv
import io
import json
import os
from datetime import date
from pathlib import Path

from django.conf import settings

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = "reports-dev-secret"
REPORT_TOKEN = "reports-admin"
DATABASE_PATH = os.environ.get("REPORTS_DB", str(BASE_DIR / "reports.sqlite3"))

if not settings.configured:
    settings.configure(
        SECRET_KEY=SECRET_KEY,
        DEBUG=True,
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
        ],
        MIDDLEWARE=[],
        TEMPLATES=[],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": DATABASE_PATH,
            }
        },
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    )

import django

django.setup()

from django.core.management import execute_from_command_line
from django.db import connection, models
from django.db.models import Case, Count, IntegerField, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt


class Event(models.Model):
    event_type = models.CharField(max_length=16)
    occurred_on = models.DateField()
    category = models.CharField(max_length=64)
    amount = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "reports_app"
        db_table = "reports_event"


class ReportRun(models.Model):
    export_format = models.CharField(max_length=8)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    category = models.CharField(max_length=64, blank=True)
    total_groups = models.IntegerField(default=0)
    returned_rows = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "reports_app"
        db_table = "reports_report_run"


EVENT_TYPES = {"sale", "refund"}


def ensure_schema() -> None:
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        if Event._meta.db_table not in existing:
            editor.create_model(Event)
            existing.add(Event._meta.db_table)
        if ReportRun._meta.db_table not in existing:
            editor.create_model(ReportRun)
            existing.add(ReportRun._meta.db_table)


ensure_schema()


def reset_database() -> None:
    connection.close()
    db_path = Path(settings.DATABASES["default"]["NAME"])
    if db_path.exists():
        db_path.unlink()
    ensure_schema()


def _json_body(request: HttpRequest) -> tuple[dict[str, object] | None, JsonResponse | None]:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return None, JsonResponse({"detail": "invalid json body"}, status=400)
    if not isinstance(payload, dict):
        return None, JsonResponse({"detail": "json object required"}, status=400)
    return payload, None


def _parse_positive_int(raw: str | None, *, name: str, default: int) -> tuple[int | None, JsonResponse | None]:
    if raw in (None, ""):
        return default, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, JsonResponse({"detail": f"{name} must be an integer"}, status=400)
    if value < 1:
        return None, JsonResponse({"detail": f"{name} must be positive"}, status=400)
    return value, None


def _parse_date(raw: str | None, *, name: str) -> tuple[date | None, JsonResponse | None]:
    if raw in (None, ""):
        return None, None
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, JsonResponse({"detail": f"{name} must be YYYY-MM-DD"}, status=400)


def _require_report_token(request: HttpRequest) -> JsonResponse | None:
    if request.headers.get("X-Report-Token") != REPORT_TOKEN:
        return JsonResponse({"detail": "report token required"}, status=401)
    return None


def _serialize_event(event: Event) -> dict[str, object]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "occurred_on": event.occurred_on.isoformat(),
        "category": event.category,
        "amount": event.amount,
        "created_at": event.created_at.replace(microsecond=0).isoformat(),
    }


def _serialize_run(run: ReportRun) -> dict[str, object]:
    return {
        "id": run.id,
        "format": run.export_format,
        "start_date": run.start_date.isoformat() if run.start_date else None,
        "end_date": run.end_date.isoformat() if run.end_date else None,
        "category": run.category or None,
        "total_groups": run.total_groups,
        "returned_rows": run.returned_rows,
        "created_at": run.created_at.replace(microsecond=0).isoformat(),
    }


def _paginate(items: list[dict[str, object]], page: int, page_size: int) -> list[dict[str, object]]:
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end]


def homepage(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <title>Reports</title>
          </head>
          <body>
            <h1>Reports</h1>
            <p>Use the browser controls below to inspect the event ingest and reporting routes.</p>
            <section>
              <h2>Event ingest</h2>
              <form action="/events" method="post">
                <label>Event type <input name="event_type" type="text" value="sale" /></label>
                <label>Occurred on <input name="occurred_on" type="date" value="2024-05-01" /></label>
                <label>Category <input name="category" type="text" value="books" /></label>
                <label>Amount <input name="amount" type="number" min="1" value="1200" /></label>
                <button type="submit">POST /events</button>
              </form>
            </section>
            <section>
              <h2>Summary</h2>
              <form action="/reports/summary" method="get">
                <label>Report token <input name="report_token" type="text" value="reports-admin" aria-label="X-Report-Token" /></label>
                <label>Start date <input name="start_date" type="date" /></label>
                <label>End date <input name="end_date" type="date" /></label>
                <label>Category <input name="category" type="text" /></label>
                <label>Page <input name="page" type="number" min="1" value="1" /></label>
                <label>Page size <input name="page_size" type="number" min="1" value="20" /></label>
                <label>Format
                  <select name="format">
                    <option value="json">json</option>
                    <option value="csv">csv</option>
                  </select>
                </label>
                <button type="submit">GET /reports/summary</button>
              </form>
              <p>Send <code>X-Report-Token: reports-admin</code> when calling <code>/reports/summary?format=csv</code>.</p>
            </section>
            <section>
              <h2>History</h2>
              <form action="/reports/history" method="get">
                <label>Page <input name="page" type="number" min="1" value="1" /></label>
                <label>Page size <input name="page_size" type="number" min="1" value="20" /></label>
                <button type="submit">GET /reports/history</button>
              </form>
              <p>History route reference: <code>/reports/history</code></p>
            </section>
          </body>
        </html>
        """.strip(),
        content_type="text/html",
    )


@csrf_exempt
def ingest_event(request: HttpRequest) -> JsonResponse:
    ensure_schema()
    if request.method != "POST":
        return JsonResponse({"detail": "method not allowed"}, status=405)

    payload, error = _json_body(request)
    if error is not None:
        return error
    assert payload is not None

    errors: dict[str, str] = {}
    event_type = str(payload.get("event_type") or "").strip()
    if event_type not in EVENT_TYPES:
        errors["event_type"] = "must be sale or refund"

    occurred_raw = str(payload.get("occurred_on") or "").strip()
    try:
        occurred_on = date.fromisoformat(occurred_raw)
    except ValueError:
        occurred_on = None
        errors["occurred_on"] = "must be YYYY-MM-DD"

    category = str(payload.get("category") or "").strip()
    if not category:
        errors["category"] = "is required"

    amount = payload.get("amount")
    if not isinstance(amount, int) or amount <= 0:
        errors["amount"] = "must be a positive integer"

    if errors:
        return JsonResponse({"detail": "invalid payload", "errors": errors}, status=400)

    event = Event.objects.create(
        event_type=event_type,
        occurred_on=occurred_on,
        category=category,
        amount=amount,
    )
    return JsonResponse(_serialize_event(event), status=201)


@csrf_exempt
def summary_report(request: HttpRequest) -> HttpResponse:
    ensure_schema()
    auth_error = _require_report_token(request)
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return JsonResponse({"detail": "method not allowed"}, status=405)

    page, error = _parse_positive_int(request.GET.get("page"), name="page", default=1)
    if error is not None:
        return error
    page_size, error = _parse_positive_int(request.GET.get("page_size"), name="page_size", default=20)
    if error is not None:
        return error
    start_date, error = _parse_date(request.GET.get("start_date"), name="start_date")
    if error is not None:
        return error
    end_date, error = _parse_date(request.GET.get("end_date"), name="end_date")
    if error is not None:
        return error
    if start_date and end_date and start_date > end_date:
        return JsonResponse({"detail": "start_date must be on or before end_date"}, status=400)

    category = (request.GET.get("category") or "").strip()
    export_format = (request.GET.get("format") or "json").strip().lower()
    if export_format not in {"json", "csv"}:
        return JsonResponse({"detail": "format must be json or csv"}, status=400)

    queryset = Event.objects.all()
    if start_date is not None:
        queryset = queryset.filter(occurred_on__gte=start_date)
    if end_date is not None:
        queryset = queryset.filter(occurred_on__lte=end_date)
    if category:
        queryset = queryset.filter(category=category)

    grouped = list(
        queryset.values("occurred_on", "category")
        .annotate(
            sales_total=Coalesce(
                Sum(Case(When(event_type="sale", then="amount"), default=Value(0), output_field=IntegerField())),
                0,
            ),
            refund_total=Coalesce(
                Sum(Case(When(event_type="refund", then="amount"), default=Value(0), output_field=IntegerField())),
                0,
            ),
            event_count=Count("id"),
        )
        .order_by("-occurred_on", "category")
    )
    items = [
        {
            "date": row["occurred_on"].isoformat(),
            "category": row["category"],
            "sales_total": int(row["sales_total"]),
            "refund_total": int(row["refund_total"]),
            "net_total": int(row["sales_total"]) - int(row["refund_total"]),
            "event_count": int(row["event_count"]),
        }
        for row in grouped
    ]
    assert page is not None
    assert page_size is not None
    paged_items = _paginate(items, page, page_size)

    ReportRun.objects.create(
        export_format=export_format,
        start_date=start_date,
        end_date=end_date,
        category=category,
        total_groups=len(items),
        returned_rows=len(paged_items),
    )

    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["date", "category", "sales_total", "refund_total", "net_total", "event_count"],
        )
        writer.writeheader()
        writer.writerows(paged_items)
        return HttpResponse(buffer.getvalue(), content_type="text/csv")

    return JsonResponse(
        {
            "items": paged_items,
            "total": len(items),
            "page": page,
            "page_size": page_size,
        }
    )


@csrf_exempt
def report_history(request: HttpRequest) -> JsonResponse:
    ensure_schema()
    auth_error = _require_report_token(request)
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return JsonResponse({"detail": "method not allowed"}, status=405)

    page, error = _parse_positive_int(request.GET.get("page"), name="page", default=1)
    if error is not None:
        return error
    page_size, error = _parse_positive_int(request.GET.get("page_size"), name="page_size", default=20)
    if error is not None:
        return error
    assert page is not None
    assert page_size is not None

    runs = [_serialize_run(run) for run in ReportRun.objects.order_by("-created_at", "-id")]
    return JsonResponse(
        {
            "items": _paginate(runs, page, page_size),
            "total": len(runs),
            "page": page,
            "page_size": page_size,
        }
    )


urlpatterns = [
    path("", homepage),
    path("events", ingest_event),
    path("reports/summary", summary_report),
    path("reports/history", report_history),
]


if __name__ == "__main__":
    execute_from_command_line()
