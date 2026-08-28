"""Container runtime helpers and command dispatch for orchestra-bench."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from bench.paths import validate_task_id
from bench.tasks import TaskDefinition
from bench.workspace import visible_task_files


# Long-lived benchmark container defaults (V1 build-env/start-env semantics,
# re-implemented in Python so the public CLI owns them).
DEFAULT_IMAGE_NAME = "orchestra-bench-env"
CONTAINER_NAME = "orchestra-bench-runner"
PROJECT_CATALOG_RELPATH = Path("config") / "orchestra" / "agent-catalog.yaml"
VISIBLE_TASKS_SOURCE_ROOTS = (Path("V1") / "tasks", Path("tasks"))
VISIBLE_TASKS_TARGET = Path("/bench/task-materials-visible")
ORCHESTRA_CATALOG_TARGET = Path("/bench/orchestra-config/agent-catalog.yaml")


def _now_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _path(value: object) -> Path:
    return Path(str(value)).expanduser()


@dataclass(frozen=True)
class RuntimeEnvironment:
    tasks_root: Path
    results_root: Path
    artifacts_root: Path
    workspace_root: Path
    orchestra_config_src: Path
    lmstudio_config_src: Path
    pi_skills_src: Path
    orchestra_runtime_dir: Path
    lmstudio_runtime_file: Path
    run_id: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeEnvironment":
        env = os.environ if environ is None else environ
        run_id = str(env.get("BENCH_RUN_ID") or _now_run_id())
        workspace_root = _path(env.get("BENCH_WORKSPACE", "/workspace"))
        shared_pi_agent_dir = workspace_root / ".pi" / "agent"
        pi_agent_dir = _path(env.get("PI_CODING_AGENT_DIR", shared_pi_agent_dir / run_id))
        if pi_agent_dir == shared_pi_agent_dir:
            raise ValueError(f"PI_CODING_AGENT_DIR must be run-scoped, not shared: {pi_agent_dir}")
        return cls(
            tasks_root=_path(env.get("BENCH_TASKS", "/bench/task-materials-visible")),
            results_root=_path(env.get("BENCH_RESULTS", "/bench/results")),
            artifacts_root=_path(env.get("BENCH_ARTIFACTS", "/bench/artifacts")),
            workspace_root=workspace_root,
            orchestra_config_src=_path(env.get("BENCH_ORCHESTRA_CONFIG_SRC", "/bench/orchestra-config")),
            lmstudio_config_src=_path(env.get("BENCH_LMSTUDIO_CONFIG_SRC", "/bench/pi/lmstudio.json")),
            pi_skills_src=_path(env.get("BENCH_PI_SKILLS_SRC", "/bench/skills")),
            orchestra_runtime_dir=_path(env.get("PI_ORCHESTRA_RUNTIME_DIR", pi_agent_dir / "orchestra")),
            lmstudio_runtime_file=_path(env.get("PI_LMSTUDIO_RUNTIME_FILE", pi_agent_dir / "lmstudio.json")),
            run_id=run_id,
        )

    def workdir(self, task_id: str) -> Path:
        return self.workspace_root / f"{self.run_id}-{task_id}"

    @property
    def pi_skills_runtime_dir(self) -> Path:
        return self.orchestra_runtime_dir.parent / "skills"


def _copy_file(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _copy_tree_overlay(source: Path, target: Path) -> Path:
    if not source.exists():
        return target
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _load_visible_task(task_id: str, tasks_root: Path) -> TaskDefinition:
    task_id = validate_task_id(task_id)
    task_dir = tasks_root / task_id
    task_yaml_path = task_dir / "task.yaml"
    if not task_yaml_path.is_file():
        raise FileNotFoundError(f"task.yaml not found: {task_yaml_path}")

    data = yaml.safe_load(task_yaml_path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"task.yaml must contain a mapping: {task_yaml_path}")

    def _require_text(key: str, default: str | None = None) -> str:
        value = data.get(key, default)
        if value is None:
            raise ValueError(f"task.yaml missing required field {key!r}: {task_yaml_path}")
        if not isinstance(value, str):
            raise ValueError(f"task.yaml field {key!r} must be a string: {task_yaml_path}")
        value = value.strip()
        if not value and default is None:
            raise ValueError(f"task.yaml field {key!r} must not be empty: {task_yaml_path}")
        return value if value else (default or "")

    def _require_int(key: str, default: int) -> int:
        value = data.get(key, default)
        try:
            timeout = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"task.yaml field {key!r} must be an integer: {task_yaml_path}") from exc
        if timeout <= 0:
            raise ValueError(f"task.yaml field {key!r} must be positive: {task_yaml_path}")
        return timeout

    prd_path = task_dir / "PRD.md"
    prompt_path = task_dir / "Prompt.md"
    fixture_path = task_dir / "fixture" if (task_dir / "fixture").is_dir() else None
    kb_dir_path = task_dir / "kb" if (task_dir / "kb").is_dir() else None
    kb_md_path = task_dir / "kb.md" if (task_dir / "kb.md").is_file() else None
    evaluate_path = task_dir / "evaluate"

    if not prd_path.is_file():
        raise FileNotFoundError(f"missing PRD.md: {prd_path}")
    if not prompt_path.is_file():
        raise FileNotFoundError(f"missing Prompt.md: {prompt_path}")
    if evaluate_path.exists():
        raise ValueError(f"visible task root must not expose evaluate: {evaluate_path}")

    return TaskDefinition(
        task_id=validate_task_id(_require_text("task_id")),
        description=_require_text("description", default=""),
        family=_require_text("family", default="default"),
        batch=_require_text("batch", default=""),
        scoring_type=_require_text("scoring_type", default="pass_fail"),
        timeout_minutes=_require_int("timeout_minutes", default=10),
        evaluator=_require_text("evaluator", default="evaluate/run.sh"),
        split=_require_text("split", default="dev"),
        task_dir=task_dir,
        task_yaml_path=task_yaml_path,
        prd_path=prd_path,
        prompt_path=prompt_path,
        fixture_path=fixture_path,
        kb_dir_path=kb_dir_path,
        kb_md_path=kb_md_path,
        evaluate_path=evaluate_path,
    )


def _require_orchestra_catalog_source(env: RuntimeEnvironment) -> Path:
    source = env.orchestra_config_src
    if not source.is_dir():
        raise FileNotFoundError(f"orchestra config source not found: {source}")
    catalog = source / "agent-catalog.yaml"
    if not catalog.is_file():
        raise FileNotFoundError(f"missing orchestra catalog: {catalog}")
    return catalog


def sync_runtime_config(env: RuntimeEnvironment) -> dict[str, object]:
    """Copy benchmark-owned runtime inputs into the live Pi/Orchestra runtime."""
    catalog_source = _require_orchestra_catalog_source(env)
    shutil.rmtree(env.orchestra_runtime_dir.parent, ignore_errors=True)
    env.orchestra_runtime_dir.mkdir(parents=True, exist_ok=True)
    env.lmstudio_runtime_file.parent.mkdir(parents=True, exist_ok=True)

    init_env = os.environ.copy()
    init_env.update(
        {
            "PI_CODING_AGENT_DIR": str(env.orchestra_runtime_dir.parent),
            "PI_ORCHESTRA_RUNTIME_DIR": str(env.orchestra_runtime_dir),
            "PI_LMSTUDIO_RUNTIME_FILE": str(env.lmstudio_runtime_file),
        }
    )
    subprocess.run(["orchestra", "init", "pi", "--copy", "--force"], check=True, env=init_env)

    catalog_target = _copy_file(catalog_source, env.orchestra_runtime_dir / "agent-catalog.yaml")
    lmstudio_target = _copy_file(env.lmstudio_config_src, env.lmstudio_runtime_file)
    skills_target = _copy_tree_overlay(env.pi_skills_src, env.pi_skills_runtime_dir)

    return {
        "orchestra_runtime_dir": str(env.orchestra_runtime_dir),
        "catalog_path": str(catalog_target),
        "lmstudio_runtime_file": str(lmstudio_target),
        "skills_dir": str(skills_target),
    }


def init_runtime(env: RuntimeEnvironment) -> dict[str, object]:
    return sync_runtime_config(env)


def _require_docker() -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("docker executable not found on PATH; install Docker before using start build/start/recreate")
    return executable


def _run_docker(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run([_require_docker(), *args], capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"docker {' '.join(args[:2])} failed ({completed.returncode}): {detail}")
    return completed


def container_exec(
    command: Sequence[str],
    *,
    container_name: str = CONTAINER_NAME,
    workdir: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    verbose: bool = False,
) -> subprocess.CompletedProcess[str]:
    docker_command = [_require_docker(), "exec"]
    if env:
        for key, value in env.items():
            docker_command.extend(["-e", f"{key}={value}"])
    if workdir is not None:
        docker_command.extend(["-w", str(workdir)])
    docker_command.append(container_name)
    docker_command.extend(str(part) for part in command)
    run_kwargs: dict[str, object] = {"text": True}
    if not verbose:
        run_kwargs["capture_output"] = True
    completed = subprocess.run(docker_command, **run_kwargs)
    return completed


def _image_name(image_name: str | None) -> str:
    if image_name:
        return image_name
    env_name = os.environ.get("BENCH_IMAGE_NAME", "").strip()
    return env_name or DEFAULT_IMAGE_NAME


def build_image(root: Path | str = ".", image_name: str | None = None) -> dict[str, object]:
    """Build the shared benchmark image from this repository tree."""
    root_path = Path(root).expanduser().resolve()
    dockerfile = root_path / "docker" / "Dockerfile"
    if not dockerfile.is_file():
        raise FileNotFoundError(f"docker/Dockerfile not found under {root_path}")
    settings = root_path / "config" / "pi" / "settings.json"
    if not settings.is_file():
        raise FileNotFoundError("Docker build input missing: config/pi/settings.json (required by docker/Dockerfile)")
    skills_dir = root_path / "config" / "skills"
    if not skills_dir.is_dir():
        raise FileNotFoundError("Docker build input missing: config/skills/ (required by docker/Dockerfile)")
    image = _image_name(image_name)
    cache_bust = str(int(time.time()))
    _run_docker(
        [
            "build",
            "--build-arg", f"SOURCE_PLUGIN_CACHE_BUST={cache_bust}",
            "-f", str(dockerfile),
            "-t", image,
            str(root_path),
        ]
    )
    return {"action": "build", "image": image, "root": str(root_path)}


def _container_state(container_name: str) -> str:
    completed = subprocess.run(
        [_require_docker(), "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return "missing"
    return "running" if completed.stdout.strip() == "true" else "stopped"


def _require_image(image: str) -> None:
    completed = subprocess.run([_require_docker(), "image", "inspect", image], capture_output=True, text=True)
    if completed.returncode != 0:
        raise FileNotFoundError(f"benchmark image {image!r} not found — run 'scripts/01-start build' first")


def _project_catalog_source(root: Path) -> Path:
    catalog = root / PROJECT_CATALOG_RELPATH
    if not catalog.is_file():
        raise FileNotFoundError(
            f"benchmark catalog copy missing at {catalog} — copy ~/workspace/orchestra/agent-catalog.yaml into config/orchestra/ once before starting the container"
        )
    return catalog


def _tasks_mount_source(root: Path) -> Path:
    for relative in VISIBLE_TASKS_SOURCE_ROOTS:
        source = root / relative
        if source.is_dir():
            return source
    missing = " or ".join(str(root / relative) for relative in VISIBLE_TASKS_SOURCE_ROOTS)
    raise FileNotFoundError(f"visible task source missing: {missing}")


def _container_mounts(root: Path, catalog: Path) -> list[str]:
    lmstudio_config = root / "config" / "pi" / "lmstudio.json"
    skills_dir = root / "config" / "skills"
    tasks_dir = _tasks_mount_source(root)
    if not lmstudio_config.is_file():
        raise FileNotFoundError(f"container mount source missing: {lmstudio_config}")
    if not skills_dir.is_dir():
        raise FileNotFoundError(f"container mount source missing: {skills_dir}")
    return [
        "-v", f"{root / 'results'}:/bench/results",
        "-v", f"{root / 'artifacts'}:/bench/artifacts",
        "-v", f"{catalog}:{ORCHESTRA_CATALOG_TARGET}:ro",
        "-v", f"{lmstudio_config}:/bench/pi/lmstudio.json:ro",
        "-v", f"{skills_dir}:/bench/skills:ro",
        "-v", f"{tasks_dir}:{VISIBLE_TASKS_TARGET}:ro",
    ]


def _create_container(root: Path, image: str) -> None:
    (root / "results").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    catalog = _project_catalog_source(root)
    mounts = _container_mounts(root, catalog)
    _run_docker(["run", "-d", "--name", CONTAINER_NAME, *mounts, image])


def start_container(
    root: Path | str = ".",
    image_name: str | None = None,
    container_name: str = CONTAINER_NAME,
) -> dict[str, object]:
    """Start or reuse the long-lived benchmark container."""
    root_path = Path(root).expanduser().resolve()
    image = _image_name(image_name)
    state = _container_state(container_name)
    if state == "running":
        return {"action": "reuse", "container": container_name, "image": image}
    _require_image(image)
    if state == "stopped":
        _run_docker(["start", container_name])
        return {"action": "start", "container": container_name, "image": image}
    _create_container(root_path, image)
    return {"action": "create", "container": container_name, "image": image}


def recreate_container(
    root: Path | str = ".",
    image_name: str | None = None,
    container_name: str = CONTAINER_NAME,
) -> dict[str, object]:
    """Remove any existing benchmark container and start a fresh one."""
    root_path = Path(root).expanduser().resolve()
    image = _image_name(image_name)
    _require_image(image)
    if _container_state(container_name) != "missing":
        # Best-effort removal, matching V1 `docker rm -f ... || true`.
        subprocess.run([_require_docker(), "rm", "-f", container_name], capture_output=True, text=True)
    _create_container(root_path, image)
    return {"action": "recreate", "container": container_name, "image": image}


def prepare_workdir(task_id: str, env: RuntimeEnvironment | None = None) -> Path:
    runtime = RuntimeEnvironment.from_env() if env is None else env
    task = _load_visible_task(task_id, runtime.tasks_root)
    workdir = runtime.workdir(task.task_id)
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    for source, relative_target in visible_task_files(task):
        target = workdir / relative_target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    return workdir


def run_in_workdir(task_id: str, command: Sequence[str] | None = None, env: RuntimeEnvironment | None = None) -> int:
    runtime = RuntimeEnvironment.from_env() if env is None else env
    workdir = runtime.workdir(task_id)
    if not workdir.is_dir():
        raise FileNotFoundError(f"workdir not found: {workdir}")
    if command is None or len(command) == 0:
        print(workdir)
        return 0
    completed = subprocess.run(list(command), cwd=workdir)
    return completed.returncode


def cleanup_workdir(task_id: str | None = None, env: RuntimeEnvironment | None = None) -> list[Path]:
    runtime = RuntimeEnvironment.from_env() if env is None else env
    removed: list[Path] = []
    if task_id:
        workdir = runtime.workdir(task_id)
        shutil.rmtree(workdir, ignore_errors=True)
        removed.append(workdir)
        return removed

    if not runtime.workspace_root.exists():
        return removed

    run_dir_pattern = re.compile(r"^\d{8}T\d{6}-")
    for entry in sorted(runtime.workspace_root.iterdir()):
        if entry.is_dir() and run_dir_pattern.match(entry.name):
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry)
    return removed


def doctor(env: RuntimeEnvironment | None = None) -> int:
    runtime = RuntimeEnvironment.from_env() if env is None else env
    report: dict[str, Any] = {
        "pi": shutil.which("pi") is not None,
        "orchestra": shutil.which("orchestra") is not None,
        "catalog": (runtime.orchestra_runtime_dir / "agent-catalog.yaml").is_file(),
        "lmstudio": runtime.lmstudio_runtime_file.is_file(),
        "runtime_dir": runtime.orchestra_runtime_dir.is_dir(),
    }

    if report["orchestra"]:
        subprocess.run(["orchestra", "doctor"], check=True)
    if report["pi"]:
        subprocess.run(["pi", "--version"], check=True)

    print(json.dumps(report, sort_keys=True))
    return 0 if all(report.values()) else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench.runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-runtime")

    prepare = subparsers.add_parser("prepare-workdir")
    prepare.add_argument("task_id")
    prepare.add_argument("extra", nargs=argparse.REMAINDER)

    evaluate = subparsers.add_parser("eval")
    evaluate.add_argument("task_id")
    evaluate.add_argument("extra", nargs=argparse.REMAINDER)

    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("task_id", nargs="?")

    subparsers.add_parser("doctor")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    env = RuntimeEnvironment.from_env()

    if args.command == "init-runtime":
        sync_runtime_config(env)
        return 0
    if args.command == "prepare-workdir":
        workdir = prepare_workdir(args.task_id, env)
        if args.extra:
            return run_in_workdir(args.task_id, args.extra, env)
        print(workdir)
        return 0
    if args.command == "eval":
        return run_in_workdir(args.task_id, args.extra or None, env)
    if args.command == "cleanup":
        removed = cleanup_workdir(args.task_id, env)
        print("\n".join(str(path) for path in removed))
        return 0
    if args.command == "doctor":
        return doctor(env)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
