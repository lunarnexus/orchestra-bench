"""Focused tests for the third capability-normal Django reporting task."""

from __future__ import annotations

import json
import os
import shutil
import subprocess as sp
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASK_ID = "cap-normal-django-reports"
_TASK_DIR = _REPO_ROOT / "tasks" / _TASK_ID


_IN_MEMORY_APP = '''from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management import execute_from_command_line
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = "reports-dev-secret"
ADMIN_TOKEN = "reports-admin"
EVENTS: list[dict[str, object]] = []
REPORT_RUNS: list[dict[str, object]] = []

if not settings.configured:
    settings.configure(
        SECRET_KEY=SECRET_KEY,
        DEBUG=True,
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth"],
        MIDDLEWARE=[],
        TEMPLATES=[],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(BASE_DIR / "db.sqlite3")}},
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    )

import django

django.setup()


def _json_body(request):
    return json.loads(request.body.decode("utf-8") or "{}")


def _require_admin(request):
    return request.headers.get("X-Report-Token") == ADMIN_TOKEN


@csrf_exempt
def ingest_event(request):
    if request.method != "POST":
        return JsonResponse({"detail": "method not allowed"}, status=405)
    payload = _json_body(request)
    if not all(payload.get(key) for key in ["event_type", "occurred_on", "category"]):
        return JsonResponse({"detail": "invalid payload"}, status=400)
    if "amount" not in payload:
        return JsonResponse({"detail": "invalid payload"}, status=400)
    event = {
        "id": len(EVENTS) + 1,
        "event_type": payload["event_type"],
        "occurred_on": payload["occurred_on"],
        "category": payload["category"],
        "amount": payload["amount"],
    }
    EVENTS.append(event)
    return JsonResponse(event, status=201)


@csrf_exempt
def summary_report(request):
    if not _require_admin(request):
        return JsonResponse({"detail": "report token required"}, status=401)
    grouped = {}
    for event in EVENTS:
        key = (event["occurred_on"], event["category"])
        bucket = grouped.setdefault(key, {
            "date": event["occurred_on"],
            "category": event["category"],
            "sales_total": 0,
            "refund_total": 0,
            "net_total": 0,
            "event_count": 0,
        })
        amount = int(event["amount"])
        if event["event_type"] == "sale":
            bucket["sales_total"] += amount
            bucket["net_total"] += amount
        else:
            bucket["refund_total"] += amount
            bucket["net_total"] -= amount
        bucket["event_count"] += 1
    items = sorted(grouped.values(), key=lambda item: (item["date"], item["category"]))
    REPORT_RUNS.append({"id": len(REPORT_RUNS) + 1, "format": request.GET.get("format", "json"), "result_count": len(items)})
    if request.GET.get("format") == "csv":
        lines = ["date,category,sales_total,refund_total,net_total,event_count"]
        for item in items:
            lines.append(f'{item["date"]},{item["category"]},{item["sales_total"]},{item["refund_total"]},{item["net_total"]},{item["event_count"]}')
        return HttpResponse("\\n".join(lines) + "\\n", content_type="text/csv")
    return JsonResponse({"items": items, "total": len(items), "page": 1, "page_size": len(items) or 1})


@csrf_exempt
def report_history(request):
    if not _require_admin(request):
        return JsonResponse({"detail": "report token required"}, status=401)
    return JsonResponse({"items": list(reversed(REPORT_RUNS)), "total": len(REPORT_RUNS), "page": 1, "page_size": len(REPORT_RUNS) or 1})


urlpatterns = [
    path("events", ingest_event),
    path("reports/summary", summary_report),
    path("reports/history", report_history),
]


if __name__ == "__main__":
    execute_from_command_line()
'''


def _copy_tree(src: Path, dest: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _run_evaluator(workspace: Path) -> tuple[int, dict]:
    env = os.environ.copy()
    env["BENCH_REPO_ROOT"] = str(_REPO_ROOT)
    env["BENCH_TASKS"] = str(_REPO_ROOT / "tasks")
    env["BENCH_CURRENT_TASK"] = _TASK_ID
    result = sp.run(
        ["bash", str(_TASK_DIR / "evaluate" / "run.sh")],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
    )
    stdout = result.stdout.strip()
    start = stdout.find("{")
    if start < 0:
        raise AssertionError(f"evaluator produced no JSON\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.returncode, json.loads(stdout[start:])


def _write_stub_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "plan steps tests files",
        "RESEARCH.md": "research source decision tradeoff",
        "VERIFY.md": "verify test pass result manage.py reports/views.py tests/test_reports.py",
        "REVIEW.md": "review risk issue follow-up",
        "APPSEC.md": "security auth input validation",
    }.items():
        (workspace / name).write_text(text)


def _write_labeled_filler_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "1. Step has POST /events and GET /reports/summary for noted work.\n2. Step has GET /reports/history and tests/test_reports.py for noted work.",
        "RESEARCH.md": "source: kb and api contract are listed for the task.\ndecision: Django sqlite3 is listed as the decision.\ntradeoff: fixture tests and tradeoff are listed for the task.",
        "VERIFY.md": "command: pytest -q tests/test_reports.py\nresult: passed and manage.py reports/views.py tests/test_reports.py pagination csv json are listed.",
        "REVIEW.md": "finding: permission status codes schema pagination history and /reports/* are listed here.\nrisk: status codes and schema risk are listed here.",
        "APPSEC.md": "threat: X-Report-Token auth validation sqlite parameter export are listed here.\nmitigation: parameter binding validation and pagination are listed here.",
    }.items():
        (workspace / name).write_text(text)


def _write_semantically_equivalent_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "1. Step implements POST /events plus GET /reports/summary with Event aggregation, ReportHistory persistence, and an _ensure_tables helper for SQLite setup.\n2. Step keeps GET /reports/history in manage.py with tests/test_reports.py coverage and verifies the workflow with python -m pytest tests/test_reports.py -v.",
        "RESEARCH.md": "source: kb/api_contract.md and kb/persistence_notes.md define the endpoints, X-Report-Token requirement, and reload expectations.\ndecision: use Django with sqlite3, django.db.models, and schema_editor so the app stays file-backed with no network dependency.\ntradeoff: keep the fixture compact by configuring models in manage.py instead of building a full migration tree.",
        "VERIFY.md": "command: python -m pytest tests/test_reports.py -v\nresult: passed for manage.py and tests/test_reports.py, covering SQLite persistence, reports/history audit rows, csv/json output, validation, and permissions.",
        "REVIEW.md": "finding: /reports/* stays behind check_report_token and X-Report-Token, while POST /events remains public and keeps status codes explicit per the API contract.\nrisk: if Event aggregates do not persist ReportHistory rows, pagination, status codes, and report history can drift after reloads.",
        "APPSEC.md": "threat: report endpoints expose sensitive aggregates unless auth via check_report_token rejects missing X-Report-Token headers, and input validation stays enforced.\nmitigation: validate date and pagination inputs before parameterized ORM filters, keep CSV export under the same rules, and store only Event and ReportHistory data in SQLite for security review.",
    }.items():
        (workspace / name).write_text(text)


def _write_dogfood_style_workflow_artifacts(workspace: Path) -> None:
    for name, text in {
        "PLAN.md": "# Plan — Django Reports App\n\n## Architecture Overview\nSingle-module Django app backed by SQLite in manage.py.\n\n## API Endpoints\n1. POST /events ingests sale and refund rows into Event storage.\n2. GET /reports/summary groups rows, records ReportRun history, and keeps GET /reports/history paginated.\n\n## Implementation Decisions\nUse _ensure_tables for SQLite bootstrap and keep tests/test_reports.py as the focused verification target.",
        "RESEARCH.md": "# Research Notes — Django Reports App\n\n## Fixture Analysis\nThe fixture already reads REPORTS_DB and exposes /events plus /reports/history.\n\n## Test Requirements Analysis\nThe api_contract document and persistence_notes document require Django with sqlite3, grouped report history, and no network dependency.\n\n## Key Design Decisions Informed by Research\nUse Django ORM aggregation in manage.py, keep the app file-backed, and avoid a full migration tree so the fixture stays compact.",
        "VERIFY.md": "# Verification Report — Django Reports App\n\n## Test Execution Results\n```\npython -m pytest tests/test_reports.py -v\n3 passed\n```\n\n## Verification Checklist\nSQLite file creation, data persistence across restarts, csv/json output, reports/history audit rows, validation, and permissions all passed for manage.py and tests/test_reports.py.",
        "REVIEW.md": "# Code Review — Django Reports App\n\n## Structure & Organization\nThe app keeps configuration, Event and ReportRun models, schema helpers, and the /reports/* views in manage.py.\n\n## Potential Improvements\nPagination currently slices after aggregation, and report history plus status codes should stay explicit so permissions and reload behavior do not drift.",
        "APPSEC.md": "# AppSec Notes — Django Reports App\n\n## Threat Model\nReport endpoints expose sensitive aggregates unless X-Report-Token auth and input validation are enforced consistently.\n\n## Security Controls Implemented\nDjango ORM parameterized queries protect SQLite access, CSV responses stay behind the same token gate, and the app validates dates, pagination, and event payloads before running report filters.\n",
    }.items():
        (workspace / name).write_text(text)


class TestCapabilityNormalDjangoReportsTask:
    def test_task_metadata_marks_capability_workflow(self):
        text = (_TASK_DIR / "task.yaml").read_text()
        assert "task_id: cap-normal-django-reports" in text
        assert "batch: capability-normal" in text
        assert "scoring_type: numeric" in text
        assert "expected_workflow: planner,researcher,builder,verifier,reviewer,appsec" in text

    def test_pristine_fixture_fails(self, tmp_path):
        _copy_tree(_TASK_DIR / "fixture", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_event_ingest"] is False

    def test_reference_solution_passes(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["functional_browser_homepage"] is True
        assert result["checks"]["functional_event_ingest"] is True
        assert result["checks"]["functional_grouped_summary_filters"] is True
        assert result["checks"]["functional_export_json_csv"] is True
        assert result["checks"]["functional_validation_status_codes_permissions"] is True
        assert result["checks"]["functional_report_run_history"] is True
        assert result["checks"]["functional_persistence_file_backed"] is True
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True

    def test_reference_solution_is_idempotent_across_repeated_evaluator_runs(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)

        first_code, first_result = _run_evaluator(tmp_path)
        second_code, second_result = _run_evaluator(tmp_path)

        first_details = json.loads(first_result["details"])
        second_details = json.loads(second_result["details"])

        assert first_code == 0
        assert second_code == 0
        assert first_result["score"] == "pass"
        assert second_result["score"] == "pass"
        assert first_result["checks"]["functional_browser_homepage"] is True
        assert second_result["checks"]["functional_browser_homepage"] is True
        assert first_result["checks"]["functional_report_run_history"] is True
        assert second_result["checks"]["functional_report_run_history"] is True
        assert first_details["functional_details"]["history"]["total"] == 4
        assert second_details["functional_details"]["history"]["total"] == 4

    def test_missing_workflow_evidence_reduces_score_without_hard_fail(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        for name in ["PLAN.md", "RESEARCH.md", "VERIFY.md", "REVIEW.md", "APPSEC.md"]:
            (tmp_path / name).unlink()

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] == 0.7
        assert result["checks"]["plan_present"] is False
        assert result["checks"]["review_present"] is False
        assert result["checks"]["appsec_present"] is False

    def test_in_memory_reports_fail_persistence_requirement(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        (tmp_path / "manage.py").write_text(_IN_MEMORY_APP)

        code, result = _run_evaluator(tmp_path)

        assert code != 0
        assert result["score"] == "fail"
        assert result["checks"]["functional_browser_homepage"] is False
        assert result["checks"]["functional_event_ingest"] is True
        assert result["checks"]["functional_persistence_file_backed"] is False

    def test_keyword_stub_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_stub_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["verify_relevant"] is False
        assert result["checks"]["review_relevant"] is False
        assert result["checks"]["appsec_relevant"] is False

    def test_labeled_filler_workflow_artifacts_do_not_receive_full_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_labeled_filler_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] < 0.9
        assert result["checks"]["plan_relevant"] is False
        assert result["checks"]["research_relevant"] is False
        assert result["checks"]["review_relevant"] is False

    def test_semantically_equivalent_workflow_artifacts_receive_credit(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_semantically_equivalent_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["score_numeric"] >= 0.9
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True

    def test_history_row_count_alias_is_accepted(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        manage_path = tmp_path / "manage.py"
        text = manage_path.read_text()
        text = text.replace('        "returned_rows": run.returned_rows,\n', '        "row_count": run.returned_rows,\n')
        manage_path.write_text(text)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["checks"]["functional_report_run_history"] is True
        assert result["checks"]["functional_validation_status_codes_permissions"] is True

    def test_dogfood_style_workflow_artifacts_receive_credit_without_label_boilerplate(self, tmp_path):
        _copy_tree(_TASK_DIR / "evaluate" / "solved", tmp_path)
        _write_dogfood_style_workflow_artifacts(tmp_path)

        code, result = _run_evaluator(tmp_path)

        assert code == 0
        assert result["score"] == "pass"
        assert result["checks"]["plan_relevant"] is True
        assert result["checks"]["research_relevant"] is True
        assert result["checks"]["verify_relevant"] is True
        assert result["checks"]["review_relevant"] is True
        assert result["checks"]["appsec_relevant"] is True
        assert "final_summary_present" not in result["checks"]
        assert "final_summary_relevant" not in result["checks"]
