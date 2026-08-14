from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = os.environ.get("REPORTS_DB", str(BASE_DIR / "reports.sqlite3"))

if not settings.configured:
    settings.configure(
        SECRET_KEY="reports-dev-secret",
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
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def ingest_event(request):
    return JsonResponse({"detail": "not implemented"}, status=501)


@csrf_exempt
def summary_report(request):
    return JsonResponse({"detail": "not implemented"}, status=501)


@csrf_exempt
def report_history(request):
    return JsonResponse({"detail": "not implemented"}, status=501)


urlpatterns = [
    path("events", ingest_event),
    path("reports/summary", summary_report),
    path("reports/history", report_history),
]


if __name__ == "__main__":
    execute_from_command_line()
