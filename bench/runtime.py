"""Container runtime helpers and command dispatch for orchestra-bench."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

from bench.ownership import host_ownership_env
from bench.paths import validate_task_id
from bench.provenance import snapshot_aux_skills, snapshot_files, snapshot_orchestra_config
from bench.tasks import TaskDefinition
from bench.workspace import visible_task_files


# Long-lived benchmark container defaults (V1 build-env/start-env semantics,
# re-implemented in Python so the public CLI owns them).
DEFAULT_IMAGE_NAME = "orchestra-bench-env"
CONTAINER_NAME = "orchestra-bench-runner"
PROJECT_CATALOG_RELPATH = Path("config") / "orchestra" / "agent-catalog.yaml"
VISIBLE_TASKS_SOURCE_ROOTS = (Path("tasks"),)
VISIBLE_TASKS_TARGET = Path("/bench/task-materials-source")
ORCHESTRA_CONFIG_TARGET = Path("/bench/orchestra-config")
PI_CONFIG_TARGET = Path("/bench/pi")
HERMES_CONFIG_TARGET = Path("/bench/hermes")
OPENCODE_CONFIG_TARGET = Path("/bench/opencode")
SKILLS_CONFIG_TARGET = Path("/bench/skills")
HERMES_RUNTIME_DIR = Path("/root/.hermes")
OPENCODE_RUNTIME_DIR = Path("/root/.config/opencode")
CONTAINER_ROOT = Path("/bench")
CONTAINER_CONTEXT_ENV = "BENCH_IN_CONTAINER"
# Host-readable record of the last effective regular-config overlay; run
# provenance merges this summary so persisted metadata names the exact config files.
RUNTIME_CONFIG_SYNC_FILENAME = "runtime-config-sync.json"
PI_AGENT_STATE_SRC = Path("/root/.pi/agent")
DEFAULT_ORCHESTRA_EXTENSION_SRC = Path("/opt/orchestra/src/extensions/pi/orchestra")


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
    orchestra_extension_src: Path | None = None
    home_dir: Path | None = None
    pi_config_src: Path | None = None
    hermes_config_src: Path | None = None
    opencode_config_src: Path | None = None
    hermes_runtime_dir: Path = HERMES_RUNTIME_DIR
    opencode_runtime_dir: Path = OPENCODE_RUNTIME_DIR

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeEnvironment":
        env = os.environ if environ is None else environ
        run_id = str(env.get("BENCH_RUN_ID") or _now_run_id())
        workspace_root = _path(env.get("BENCH_WORKSPACE", "/workspace"))
        home_dir = _path(workspace_root / ".pi" / "home" / run_id)
        expected_pi_agent_dir = home_dir / ".pi" / "agent"
        pi_agent_dir = _path(env.get("PI_CODING_AGENT_DIR", expected_pi_agent_dir))
        if pi_agent_dir != expected_pi_agent_dir:
            raise ValueError(f"PI_CODING_AGENT_DIR must match HOME/.pi/agent: {pi_agent_dir} != {expected_pi_agent_dir}")
        lmstudio_config_src = _path(env.get("BENCH_LMSTUDIO_CONFIG_SRC", "/bench/pi/lmstudio.json"))
        return cls(
            tasks_root=_path(env.get("BENCH_TASKS", "/bench/task-materials-source")),
            results_root=_path(env.get("BENCH_RESULTS", "/bench/results")),
            artifacts_root=_path(env.get("BENCH_ARTIFACTS", "/bench/artifacts")),
            workspace_root=workspace_root,
            orchestra_config_src=_path(env.get("BENCH_ORCHESTRA_CONFIG_SRC", "/bench/orchestra-config")),
            lmstudio_config_src=lmstudio_config_src,
            pi_skills_src=_path(env.get("BENCH_PI_SKILLS_SRC", "/bench/skills")),
            orchestra_runtime_dir=_path(env.get("PI_ORCHESTRA_RUNTIME_DIR", pi_agent_dir / "orchestra")),
            lmstudio_runtime_file=_path(env.get("PI_LMSTUDIO_RUNTIME_FILE", pi_agent_dir / "lmstudio.json")),
            run_id=run_id,
            orchestra_extension_src=_path(extension_src) if (extension_src := env.get("BENCH_ORCHESTRA_EXTENSION_SRC")) else None,
            home_dir=home_dir,
            pi_config_src=_path(env.get("BENCH_PI_CONFIG_SRC", lmstudio_config_src.parent)),
            hermes_config_src=_path(env.get("BENCH_HERMES_CONFIG_SRC", "/bench/hermes")),
            opencode_config_src=_path(env.get("BENCH_OPENCODE_CONFIG_SRC", "/bench/opencode")),
            hermes_runtime_dir=_path(env.get("PI_HERMES_RUNTIME_DIR", HERMES_RUNTIME_DIR)),
            opencode_runtime_dir=_path(env.get("PI_OPENCODE_RUNTIME_DIR", OPENCODE_RUNTIME_DIR)),
        )

    def workdir(self, task_id: str) -> Path:
        return self.workspace_root / f"{self.run_id}-{task_id}"

    @property
    def pi_runtime_dir(self) -> Path:
        return self.orchestra_runtime_dir.parent

    @property
    def pi_skills_runtime_dir(self) -> Path:
        return self.orchestra_runtime_dir.parent / "skills"


def _copy_file(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _env_bool(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _copy_sanitized_orchestra_catalog(source: Path, target: Path) -> Path:
    raw = yaml.safe_load(source.read_text())
    target.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(raw, dict):
        shutil.copy2(source, target)
        return target
    roles = raw.get("roles")
    if isinstance(roles, dict):
        for role_config in roles.values():
            if isinstance(role_config, dict):
                role_config.pop("prompt_addition", None)
    target.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return target


def _copy_tree_overlay(source: Path, target: Path) -> Path:
    if not source.exists():
        return target
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _deep_merge(base: object, override: object) -> object:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return override


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _copy_pi_config_overlay(source: Path, target: Path) -> Path:
    if not source.exists():
        return target
    target.mkdir(parents=True, exist_ok=True)
    settings_source = source / "settings.json"
    for entry in source.iterdir():
        if entry.name == "settings.json":
            continue
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        elif entry.is_file():
            _copy_file(entry, destination)
    if settings_source.is_file():
        settings_target = target / "settings.json"
        merged = _deep_merge(_load_json_object(settings_target), _load_json_object(settings_source))
        settings_target.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _merge_pi_package_registration(source: Path, target: Path) -> Path:
    try:
        if not source.exists():
            return target
    except OSError:
        return target
    target.mkdir(parents=True, exist_ok=True)

    for entry_name in ("git", "extensions"):
        entry = source / entry_name
        if entry.is_dir():
            shutil.copytree(entry, target / entry_name, dirs_exist_ok=True)

    models_store = source / "models-store.json"
    if models_store.is_file():
        _copy_file(models_store, target / "models-store.json")

    source_settings = _load_json_object(source / "settings.json")
    source_packages = source_settings.get("packages")
    if not isinstance(source_packages, list):
        return target

    target_settings_path = target / "settings.json"
    target_settings = _load_json_object(target_settings_path)
    target_packages = target_settings.get("packages")
    merged_packages: list[str] = []
    seen: set[str] = set()

    for package in target_packages if isinstance(target_packages, list) else []:
        package_name = str(package).strip()
        if package_name and package_name not in seen:
            merged_packages.append(package_name)
            seen.add(package_name)
    for package in source_packages:
        package_name = str(package).strip()
        if package_name and package_name not in seen:
            merged_packages.append(package_name)
            seen.add(package_name)

    if merged_packages:
        target_settings["packages"] = merged_packages
        target_settings_path.write_text(json.dumps(target_settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _snapshot_tree(source: Path | None) -> dict[str, object]:
    if source is None:
        return {"files": [], "sha256": ""}
    return snapshot_files(source)


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


def _require_orchestra_extension_source(env: RuntimeEnvironment) -> Path:
    candidates = []
    if env.orchestra_extension_src is not None:
        candidates.append(env.orchestra_extension_src)
    else:
        candidates.extend(
            [
                Path("/bench/orchestra-extension"),
                DEFAULT_ORCHESTRA_EXTENSION_SRC,
                Path(__file__).resolve().parents[2] / "orchestra" / "extensions" / "pi" / "orchestra",
            ]
        )
    for source in candidates:
        try:
            if source.is_dir():
                return source
        except OSError:
            continue
    if env.orchestra_extension_src is not None:
        source = env.orchestra_extension_src
    else:
        source = candidates[0] if candidates else DEFAULT_ORCHESTRA_EXTENSION_SRC
    raise FileNotFoundError(f"orchestra extension source not found: {source}")


def runtime_config_sync_path(env: RuntimeEnvironment) -> Path:
    return env.artifacts_root / RUNTIME_CONFIG_SYNC_FILENAME


def runtime_config_sync_legacy_path(env: RuntimeEnvironment) -> Path:
    return env.results_root / RUNTIME_CONFIG_SYNC_FILENAME


def _apply_orchestra_tools_override(env: RuntimeEnvironment) -> bool | None:
    enabled = _env_bool(os.environ.get("BENCH_ORCHESTRA_TOOLS_DEFAULT"))
    if enabled is None:
        return None
    config_path = env.orchestra_runtime_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = dict(loaded)
    data["tools_enabled_by_default"] = enabled
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return enabled


def _persist_runtime_config_summary(env: RuntimeEnvironment, summary: dict[str, object]) -> None:
    path = runtime_config_sync_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def load_runtime_config_summary(env: RuntimeEnvironment | None = None) -> dict[str, object]:
    runtime = env if env is not None else RuntimeEnvironment.from_env()
    for path in (runtime_config_sync_path(runtime), runtime_config_sync_legacy_path(runtime)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items()}
    return {}


def sync_runtime_config(env: RuntimeEnvironment) -> dict[str, object]:
    """Copy benchmark-owned runtime inputs into the live Pi/Orchestra runtime."""
    catalog_source = _require_orchestra_catalog_source(env)
    home_dir = env.home_dir or (env.workspace_root / ".pi" / "home" / env.run_id)
    pi_runtime_dir = env.pi_runtime_dir
    pi_runtime_dir.mkdir(parents=True, exist_ok=True)
    env.orchestra_runtime_dir.mkdir(parents=True, exist_ok=True)
    env.lmstudio_runtime_file.parent.mkdir(parents=True, exist_ok=True)
    env.hermes_runtime_dir.mkdir(parents=True, exist_ok=True)
    env.opencode_runtime_dir.mkdir(parents=True, exist_ok=True)

    init_env = os.environ.copy()
    init_env.update(
        {
            "HOME": str(home_dir),
            "PI_CODING_AGENT_DIR": str(pi_runtime_dir),
            "PI_ORCHESTRA_RUNTIME_DIR": str(env.orchestra_runtime_dir),
            "PI_LMSTUDIO_RUNTIME_FILE": str(env.lmstudio_runtime_file),
        }
    )
    subprocess.run(["orchestra", "init", "pi", "--copy", "--force"], check=True, env=init_env)

    pi_source = env.pi_config_src or env.lmstudio_config_src.parent
    orchestra_target = _copy_tree_overlay(env.orchestra_config_src, env.orchestra_runtime_dir)
    catalog_target = _copy_sanitized_orchestra_catalog(catalog_source, env.orchestra_runtime_dir / "agent-catalog.yaml")
    _merge_pi_package_registration(PI_AGENT_STATE_SRC, pi_runtime_dir)
    pi_target = _copy_pi_config_overlay(pi_source, pi_runtime_dir)
    hermes_target = _copy_tree_overlay(env.hermes_config_src, env.hermes_runtime_dir) if env.hermes_config_src is not None else env.hermes_runtime_dir
    opencode_target = _copy_tree_overlay(env.opencode_config_src, env.opencode_runtime_dir) if env.opencode_config_src is not None else env.opencode_runtime_dir
    skills_target = _copy_tree_overlay(env.pi_skills_src, env.pi_skills_runtime_dir)

    validate_env = os.environ.copy()
    validate_env.update(
        {
            "HOME": str(home_dir),
            "PI_CODING_AGENT_DIR": str(pi_runtime_dir),
            "PI_ORCHESTRA_RUNTIME_DIR": str(env.orchestra_runtime_dir),
            "PI_LMSTUDIO_RUNTIME_FILE": str(env.lmstudio_runtime_file),
        }
    )
    tool_info = subprocess.run(
        ["orchestra", "_tool-info"],
        check=False,
        capture_output=True,
        text=True,
        env=validate_env,
        cwd=env.orchestra_runtime_dir,
    )
    if tool_info.returncode != 0:
        detail = (tool_info.stderr or tool_info.stdout or "").strip()
        raise RuntimeError(f"orchestra _tool-info failed ({tool_info.returncode}){': ' + detail if detail else ''}")

    orchestra_tools_enabled = _apply_orchestra_tools_override(env)
    orchestra_snapshot = snapshot_orchestra_config(env.orchestra_config_src)
    orchestra_extension_source = _require_orchestra_extension_source(env)
    orchestra_extension_target = _copy_tree_overlay(orchestra_extension_source, pi_runtime_dir / "extensions" / "orchestra")
    orchestra_extension_snapshot = _snapshot_tree(orchestra_extension_source)
    pi_snapshot = _snapshot_tree(pi_source)
    hermes_snapshot = _snapshot_tree(env.hermes_config_src)
    opencode_snapshot = _snapshot_tree(env.opencode_config_src)
    skills_snapshot = snapshot_aux_skills(env.pi_skills_src)

    summary: dict[str, object] = {
        "home_dir": str(home_dir),
        "orchestra_runtime_dir": str(env.orchestra_runtime_dir),
        "orchestra_tools_enabled_by_default": orchestra_tools_enabled,
        "pi_runtime_dir": str(pi_runtime_dir),
        "hermes_runtime_dir": str(env.hermes_runtime_dir),
        "opencode_runtime_dir": str(env.opencode_runtime_dir),
        "catalog_path": str(catalog_target),
        "orchestra_config_dir": str(orchestra_target),
        "orchestra_extension_dir": str(orchestra_extension_target),
        "orchestra_extension_files": orchestra_extension_snapshot["files"],
        "orchestra_extension_sha256": orchestra_extension_snapshot["sha256"],
        **orchestra_snapshot,
        "pi_config_dir": str(pi_target),
        "pi_config_files": pi_snapshot["files"],
        "pi_config_sha256": pi_snapshot["sha256"],
        "hermes_config_dir": str(hermes_target),
        "hermes_config_files": hermes_snapshot["files"],
        "hermes_config_sha256": hermes_snapshot["sha256"],
        "opencode_config_dir": str(opencode_target),
        "opencode_config_files": opencode_snapshot["files"],
        "opencode_config_sha256": opencode_snapshot["sha256"],
        "skills_dir": str(skills_target),
        **skills_snapshot,
    }
    _persist_runtime_config_summary(env, summary)
    return summary


def init_runtime(env: RuntimeEnvironment) -> dict[str, object]:
    return sync_runtime_config(env)


def _require_docker() -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("docker executable not found on PATH; install Docker before using start build/start/recreate")
    return executable


def _run_docker(args: Sequence[str], *, stream_output: bool = False) -> subprocess.CompletedProcess[str]:
    run_kwargs: dict[str, object] = {"text": True}
    if not stream_output:
        run_kwargs["capture_output"] = True
    completed = subprocess.run([_require_docker(), *args], **run_kwargs)
    if completed.returncode != 0:
        detail = ""
        if getattr(completed, "stderr", None):
            detail = str(completed.stderr).strip()
        elif getattr(completed, "stdout", None):
            detail = str(completed.stdout).strip()
        message = f"docker {' '.join(args[:2])} failed ({completed.returncode})"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message)
    return completed


def _build_container_exec_command(
    command: Sequence[str],
    *,
    container_name: str = CONTAINER_NAME,
    workdir: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    interactive: bool = False,
    tty: bool = False,
) -> list[str]:
    docker_command = [_require_docker(), "exec"]
    if interactive or tty:
        docker_command.append("-i")
    if tty:
        docker_command.append("-t")
    merged_env = dict(env or {})
    for key, value in host_ownership_env().items():
        merged_env.setdefault(key, value)
    for key, value in merged_env.items():
        docker_command.extend(["-e", f"{key}={value}"])
    if workdir is not None:
        docker_command.extend(["-w", str(workdir)])
    docker_command.append(container_name)
    docker_command.extend(str(part) for part in command)
    return docker_command


def container_exec(
    command: Sequence[str],
    *,
    container_name: str = CONTAINER_NAME,
    workdir: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    verbose: bool = False,
    interactive: bool = False,
    tty: bool = False,
    transcript_path: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    docker_command = _build_container_exec_command(
        command,
        container_name=container_name,
        workdir=workdir,
        env=env,
        interactive=interactive,
        tty=tty,
    )
    run_kwargs: dict[str, object] = {"text": True}
    if interactive and tty and transcript_path is not None:
        script_executable = shutil.which("script")
        if script_executable is None:
            raise RuntimeError("script executable not found on PATH; install util-linux to record interactive transcripts")
        transcript = Path(transcript_path)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        script_command = [script_executable, "-qefc", shlex.join(docker_command), str(transcript)]
        completed = subprocess.run(script_command, **run_kwargs)
        return completed
    if not verbose:
        run_kwargs["capture_output"] = True
    completed = subprocess.run(docker_command, **run_kwargs)
    return completed


def _image_name(image_name: str | None) -> str:
    if image_name:
        return image_name
    env_name = os.environ.get("BENCH_IMAGE_NAME", "").strip()
    return env_name or DEFAULT_IMAGE_NAME


def build_image(root: Path | str = ".", image_name: str | None = None, *, stream_output: bool = False) -> dict[str, object]:
    """Build the shared benchmark image from this repository tree."""
    root_path = Path(root).expanduser().resolve()
    dockerfile = root_path / "docker" / "Dockerfile"
    if not dockerfile.is_file():
        raise FileNotFoundError(f"docker/Dockerfile not found under {root_path}")
    image = _image_name(image_name)
    cache_bust = str(int(time.time()))
    _run_docker(
        [
            "build",
            "--build-arg", f"SOURCE_PLUGIN_CACHE_BUST={cache_bust}",
            "-f", str(dockerfile),
            "-t", image,
            str(root_path),
        ],
        stream_output=stream_output,
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
    source = root / VISIBLE_TASKS_SOURCE_ROOTS[0]
    if source.is_dir():
        return source
    raise FileNotFoundError(f"visible task source missing: {source}")


def _container_mounts(root: Path, catalog: Path) -> list[str]:
    orchestra_dir = root / "config" / "orchestra"
    pi_dir = root / "config" / "pi"
    hermes_dir = root / "config" / "hermes"
    opencode_dir = root / "config" / "opencode"
    skills_dir = root / "config" / "skills"
    orchestra_extension_dir = root.parent / "orchestra" / "extensions" / "pi" / "orchestra"
    tasks_dir = _tasks_mount_source(root)
    for source in (orchestra_dir, pi_dir, hermes_dir, opencode_dir, skills_dir):
        source.mkdir(parents=True, exist_ok=True)
    mounts = [
        "-v", f"{root / 'results'}:/bench/results",
        "-v", f"{root / 'artifacts'}:/bench/artifacts",
        "-v", f"{orchestra_dir}:{ORCHESTRA_CONFIG_TARGET}:ro",
        "-v", f"{pi_dir}:{PI_CONFIG_TARGET}:ro",
        "-v", f"{hermes_dir}:{HERMES_CONFIG_TARGET}:ro",
        "-v", f"{opencode_dir}:{OPENCODE_CONFIG_TARGET}:ro",
        "-v", f"{skills_dir}:{SKILLS_CONFIG_TARGET}:ro",
        "-v", f"{tasks_dir}:{VISIBLE_TASKS_TARGET}:ro",
    ]
    if orchestra_extension_dir.is_dir():
        mounts.extend(["-v", f"{orchestra_extension_dir}:/bench/orchestra-extension:ro"])
    return mounts


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


def _parse_json_summary_from_stdout(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            summary, end = decoder.raw_decode(stdout, index)
        except ValueError:
            continue
        if stdout[end:].strip():
            continue
        if not isinstance(summary, dict):
            raise RuntimeError("in-container runtime config summary must be an object")
        return {str(key): value for key, value in summary.items()}
    raise RuntimeError("in-container runtime config sync did not return a JSON summary")


def _sync_runtime_config_inside_container() -> dict[str, Any]:
    completed = container_exec(
        ["python3", "-m", "bench.runtime", "init-runtime"],
        workdir=CONTAINER_ROOT,
        env={CONTAINER_CONTEXT_ENV: "1"},
        verbose=False,
    )
    if completed.returncode != 0:
        detail = (getattr(completed, "stderr", None) or getattr(completed, "stdout", None) or "").strip()
        raise RuntimeError(f"in-container runtime config sync failed ({completed.returncode}): {detail}")
    stdout = getattr(completed, "stdout", None) or ""
    return _parse_json_summary_from_stdout(stdout)


def prepare_startup(
    root: Path | str = ".",
    image_name: str | None = None,
    container_name: str = CONTAINER_NAME,
    *,
    progress: Callable[[str], None] | None = None,
    stream_build_output: bool = False,
) -> dict[str, object]:
    if progress is not None:
        progress("Building image...")
    build_report = build_image(root=root, image_name=image_name, stream_output=stream_build_output)
    if progress is not None:
        progress("Recreating container...")
    container_report = recreate_container(root=root, image_name=image_name, container_name=container_name)
    if progress is not None:
        progress("Applying runtime config...")
    runtime_summary = _sync_runtime_config_inside_container()
    if progress is not None:
        progress("Ready.")
    return {
        "status": "ok",
        "image": build_report["image"],
        "container": container_report["container"],
        "runtime": {
            "home_dir": runtime_summary.get("home_dir"),
            "pi_runtime_dir": runtime_summary.get("pi_runtime_dir"),
            "orchestra_runtime_dir": runtime_summary.get("orchestra_runtime_dir"),
        },
    }


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
        # JSON summary on stdout lets the host-side passthrough shim discover
        # the effective run-scoped runtime dirs for interactive sessions.
        print(json.dumps(sync_runtime_config(env), indent=2, sort_keys=True))
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
