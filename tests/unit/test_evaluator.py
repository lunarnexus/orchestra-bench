from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bench.evaluator import EvaluationError, grade_run
from bench.paths import RepoPaths
from bench.result import EvaluationResult, HarnessResult, RunMeta, TaskResult, load_result, write_json_atomic
from bench.tasks import load_task
from bench.workspace import prepare_workspace


def _write_task(task_dir: Path, *, task_id: str = "alpha") -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.yaml").write_text(
        "task_id: {task_id}\n"
        "description: Sample task\n"
        "family: builder\n"
        "batch: smoke\n"
        "scoring_type: pass_fail\n"
        "timeout_minutes: 10\n"
        "evaluator: evaluate/run.sh\n".format(task_id=task_id)
    )
    (task_dir / "PRD.md").write_text("Product requirements.\n")
    (task_dir / "Prompt.md").write_text("Do the thing.\n")
    (task_dir / "fixture").mkdir()
    (task_dir / "evaluate").mkdir()
    (task_dir / "evaluate" / "run.sh").write_text("#!/bin/sh\nexit 0\n")



def test_grade_run_inherits_process_environment_for_grader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Graders rely on a sane inherited env (e.g. PATH); container python breaks with an empty env."""
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    workspace = prepare_workspace(task, run_paths)
    write_json_atomic(
        run_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="not_run"),
            outcome="not_run",
        ),
    )

    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    captured: dict[str, object] = {}

    def fake_runner(command, **kwargs):
        captured["env"] = dict(kwargs["env"])
        Path(kwargs["env"]["BENCH_RESULT_JSON"]).write_text('{"status": "ok", "score": "pass"}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    grade_run(task, run_paths, runner=fake_runner)

    env = captured["env"]
    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["BENCH_WORKDIR"] == str(workspace)


def test_grade_run_updates_result_and_captures_artifacts(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    workspace = prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(status="not_run"),
        outcome="not_run",
    )
    write_json_atomic(run_paths.result_json, original)

    captured: dict[str, object] = {}

    def fake_runner(command, **kwargs):
        captured["command"] = list(command)
        captured["cwd"] = kwargs["cwd"]
        captured["env"] = dict(kwargs["env"])

        staged_root = Path(kwargs["env"]["BENCH_REPO_ROOT"])
        assert (staged_root / "evaluate" / "run.sh").is_file()
        assert not (workspace / "evaluate").exists()

        result_json = Path(kwargs["env"]["BENCH_RESULT_JSON"])
        result_json.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "score": "pass",
                    "checks": {"workspace": True},
                    "details": {"source": "result.json"},
                }
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout="stdout line\n", stderr="stderr line\n")

    result = grade_run(task, run_paths, runner=fake_runner)

    assert result == load_result(run_paths.result_json)
    assert result.evaluation == EvaluationResult(
        status="ok",
        score="pass",
        checks={"workspace": True},
        error="",
        details={"source": "result.json"},
    )
    assert result.outcome == "pass"
    assert result.harness == original.harness
    assert captured["cwd"] == workspace
    assert captured["command"][0] == "bash"
    assert captured["command"][1].endswith("/evaluate/run.sh")
    assert Path(captured["command"][1]).name == "run.sh"
    assert (run_paths.artifacts_dir / "evaluator" / "stdout.txt").read_text(encoding="utf-8") == "stdout line\n"
    assert (run_paths.artifacts_dir / "evaluator" / "stderr.txt").read_text(encoding="utf-8") == "stderr line\n"
    assert (run_paths.artifacts_dir / "evaluator" / "log.txt").read_text(encoding="utf-8")
    assert json.loads((run_paths.manifest_path).read_text(encoding="utf-8"))["classification"] == "ok"


def test_smoke_dependent_setup_chain_evaluator_emits_structured_functionality_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "shop.py").write_text(
        """
PRODUCTS = {}
CUSTOMERS = {}
ORDERS = []

def add_product(sku, name, price):
    PRODUCTS[sku] = {'sku': sku, 'name': name, 'price': float(price)}
    return PRODUCTS[sku]

def add_customer(customer_id, name):
    CUSTOMERS[customer_id] = {'customer_id': customer_id, 'name': name, 'cart': []}
    return CUSTOMERS[customer_id]

def add_to_cart(customer_id, sku, quantity):
    CUSTOMERS[customer_id]['cart'].append({'sku': sku, 'quantity': int(quantity)})

def checkout(customer_id):
    if customer_id not in CUSTOMERS:
        raise ValueError('missing customer')
    customer = CUSTOMERS[customer_id]
    if not customer['cart']:
        raise ValueError('empty cart')
    items = []
    total = 0.0
    for line in customer['cart']:
        sku = line['sku']
        if sku not in PRODUCTS:
            raise ValueError(f'unknown product: {sku}')
        product = PRODUCTS[sku]
        quantity = int(line['quantity'])
        items.append({
            'sku': sku,
            'name': product['name'],
            'quantity': quantity,
            'unit_price': product['price'],
            'line_total': round(product['price'] * quantity, 2),
        })
        total += product['price'] * quantity
    order = {
        'order_id': f'ORD-{len(ORDERS) + 1}',
        'customer_id': customer_id,
        'items': items,
        'total': round(total, 2),
    }
    ORDERS.append(order)
    customer['cart'] = []
    return order
""".strip() + "\n",
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[2] / "tasks" / "smoke-dependent-setup-chain" / "evaluate" / "run.sh"
    completed = subprocess.run(["bash", str(script)], cwd=workspace, text=True, capture_output=True, check=False)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["score"] == "pass"
    assert payload["checks"] == payload["details"]["functionality"]["checks"]
    assert payload["details"]["functionality"]["checks"]["checkout_returns_order_shape"] is True
    assert payload["details"]["functionality"]["evidence"]["order"]["order_id"] == "ORD-1"


def test_grade_run_persists_stdout_json_to_evaluator_artifact_when_result_file_is_empty(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(status="not_run"),
        outcome="not_run",
    )
    write_json_atomic(run_paths.result_json, original)

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "status": "ok",
                    "score": "pass",
                    "checks": {"source": "stdout"},
                    "details": {"source": "stdout"},
                }
            ) + "\n",
            stderr="",
        )

    result = grade_run(task, run_paths, runner=fake_runner)

    assert result.evaluation == EvaluationResult(
        status="ok",
        score="pass",
        checks={"source": "stdout"},
        error="",
        details={"source": "stdout"},
    )
    assert result.outcome == "pass"
    assert json.loads((run_paths.artifacts_dir / "evaluator" / "result.json").read_text(encoding="utf-8")) == {
        "checks": {"source": "stdout"},
        "details": {"source": "stdout"},
        "score": "pass",
        "status": "ok",
    }
    assert load_result(run_paths.result_json).evaluation == result.evaluation


def test_grade_run_preserves_previous_result_when_evaluator_produces_no_json(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(status="not_run"),
        outcome="not_run",
    )
    write_json_atomic(run_paths.result_json, original)
    original_text = run_paths.result_json.read_text(encoding="utf-8")

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom\n")

    with pytest.raises(EvaluationError, match="no JSON") as exc_info:
        grade_run(task, run_paths, runner=fake_runner)

    assert exc_info.value.classification == "crash"
    assert run_paths.result_json.read_text(encoding="utf-8") == original_text
    assert load_result(run_paths.result_json) == original
    assert json.loads((run_paths.manifest_path).read_text(encoding="utf-8"))["classification"] == "crash"


def test_grade_run_ignores_stale_evaluator_result_when_regrade_fails(tmp_path: Path) -> None:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    original = TaskResult(
        run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
        harness=HarnessResult(status="ok", exit_code=0, details={"runner": "fake"}),
        evaluation=EvaluationResult(
            status="ok",
            score="pass",
            checks={"workspace": True},
            error="",
            details={"source": "previous-success"},
        ),
        outcome="pass",
    )
    write_json_atomic(run_paths.result_json, original)

    stale_result = run_paths.artifacts_dir / "evaluator" / "result.json"
    stale_result.parent.mkdir(parents=True, exist_ok=True)
    stale_result.write_text(
        json.dumps(
            {
                "status": "ok",
                "score": "fail",
                "checks": {"stale": True},
                "details": {"source": "stale-artifact"},
            }
        ),
        encoding="utf-8",
    )
    original_text = run_paths.result_json.read_text(encoding="utf-8")

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom\n")

    with pytest.raises(EvaluationError, match="no JSON") as exc_info:
        grade_run(task, run_paths, runner=fake_runner)

    assert exc_info.value.classification == "crash"
    assert run_paths.result_json.read_text(encoding="utf-8") == original_text
    assert load_result(run_paths.result_json) == original
    assert json.loads(stale_result.read_text(encoding="utf-8"))["details"]["source"] == "stale-artifact"
    assert json.loads((run_paths.manifest_path).read_text(encoding="utf-8"))["classification"] == "crash"


@pytest.mark.parametrize("score,expected_outcome", [("pass", "pass"), ("fail", "fail")])
def test_grade_run_derives_ok_status_when_grader_omits_explicit_status(
    tmp_path: Path, score: str, expected_outcome: str
) -> None:
    """Graders emit a verdict (score/checks/details) without an explicit status field."""
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T010203", "alpha")
    prepare_workspace(task, run_paths)
    write_json_atomic(
        run_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="not_run"),
            outcome="not_run",
        ),
    )

    def fake_runner(command, **kwargs):
        Path(kwargs["env"]["BENCH_RESULT_JSON"]).write_text(
            json.dumps({"score": score, "checks": {"workflow_passes": True}, "details": {}})
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = grade_run(task, run_paths, runner=fake_runner)

    assert result.evaluation.status == "ok"
    assert result.evaluation.score == score
    assert result.outcome == expected_outcome
    artifact_result = run_paths.artifacts_dir / "evaluator" / "result.json"
    assert artifact_result.stat().st_mode & 0o777 == 0o644


# ---------------------------------------------------------------------------
# Slice 1 — capability result-contract through the real grading path.
# The V2 contract requires details to be a JSON object; evaluators emitting
# a serialized JSON string must not silently lose functionality evidence.
# ---------------------------------------------------------------------------

_CAPABILITY_CHECKS: dict[str, bool] = {
    "functional_api_contract": True,
    "functional_persistence_roundtrip": True,
    "functional_history_endpoint": True,
    "functional_secret_not_exposed": False,
}

_CAPABILITY_DETAILS_OBJECT: dict[str, object] = {
    "functionality": {
        "checks": _CAPABILITY_CHECKS,
        "evidence": {"order": {"order_id": "ORD-1"}, "history_rows": 3},
    }
}


def _write_capability_run(tmp_path: Path) -> tuple[object, object]:
    repo = RepoPaths(tmp_path)
    task_dir = tmp_path / "tasks" / "alpha"
    _write_task(task_dir)
    task = load_task(task_dir, tmp_path / "tasks")

    run_paths = repo.run("20250101T093000", "alpha")
    prepare_workspace(task, run_paths)
    write_json_atomic(
        run_paths.result_json,
        TaskResult(
            run_meta=RunMeta(run_id=run_paths.run_id, task_id=task.task_id, batch=task.batch),
            harness=HarnessResult(status="ok", exit_code=0),
            evaluation=EvaluationResult(status="not_run"),
            outcome="not_run",
        ),
    )
    return task, run_paths


def test_grade_run_preserves_object_valued_capability_details(tmp_path: Path) -> None:
    """Canonical object-valued details survive the real grading path into result.json."""
    task, run_paths = _write_capability_run(tmp_path)

    def fake_runner(command, **kwargs):
        Path(kwargs["env"]["BENCH_RESULT_JSON"]).write_text(
            json.dumps(
                {
                    "score": "fail",
                    "checks": dict(_CAPABILITY_CHECKS),
                    "details": _CAPABILITY_DETAILS_OBJECT,
                }
            )
        )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    result = grade_run(task, run_paths, runner=fake_runner)

    assert result.outcome == "fail"
    assert result.evaluation.details["functionality"]["checks"] == _CAPABILITY_CHECKS
    assert isinstance(result.evaluation.details["functionality"]["evidence"], dict)
    persisted = load_result(run_paths.result_json).evaluation.details
    assert persisted["functionality"]["checks"] == _CAPABILITY_CHECKS


def test_grade_run_exposes_json_string_capability_details_as_contract_bug(tmp_path: Path) -> None:
    """Capability evaluators emit details as a JSON string; that must not pass silently."""
    task, run_paths = _write_capability_run(tmp_path)

    def fake_runner(command, **kwargs):
        Path(kwargs["env"]["BENCH_RESULT_JSON"]).write_text(
            json.dumps(
                {
                    "score": "fail",
                    "checks": dict(_CAPABILITY_CHECKS),
                    # Malformed per the V2 contract: details is a serialized JSON string.
                    "details": json.dumps({"functionality": {"checks": _CAPABILITY_CHECKS, "evidence": {}}}),
                }
            )
        )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    with pytest.raises(EvaluationError, match="invalid result schema"):
        grade_run(task, run_paths, runner=fake_runner)
