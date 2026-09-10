from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency is available in tests
    yaml = None  # type: ignore[assignment]
    _YAML_IMPORT_ERROR = exc
else:
    _YAML_IMPORT_ERROR = None


class CatalogConfigError(ValueError):
    """Raised when an agent catalog has an unsupported structure."""


@dataclass(frozen=True)
class HarnessConfig:
    name: str
    harness: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class RoleConfig:
    name: str
    harness_config: str
    model: str | None = None
    profile: str | None = None
    agent: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    skills: tuple[str, ...] = ()
    enabled: bool = True
    prompt_addition: str = ""
    nested_dispatch_depth: int | None = None
    turn_limit: int | None = None
    soft_timeout: int | None = None


@dataclass(frozen=True)
class BenchConfig:
    catalog_path: Path
    catalog_sha256: str
    default_role: str
    harness_configs: dict[str, HarnessConfig]
    roles: dict[str, RoleConfig]
    model_limits: dict[str, dict[str, Any]] = field(default_factory=dict)


_ROOT_KEYS = {"default_role", "harness_configs", "roles", "model_limits"}
_HARNESS_CONFIG_KEYS = {"harness", "command"}
_ROLE_KEYS = {
    "harness_config",
    "model",
    "profile",
    "agent",
    "env",
    "skills",
    "enabled",
    "prompt_addition",
    "nested_dispatch_depth",
    "turn_limit",
    "soft_timeout",
}
_MODEL_LIMIT_KEYS = {"concurrency"}


def _error(message: str) -> None:
    raise CatalogConfigError(message)


def _require_mapping(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error(f"{context} must be a mapping")
    return value


def _require_str(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(f"{context} must be a non-empty string")
    return value.strip()


def _optional_str(value: object, context: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, context)


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _require_str_list(value: object, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        _error(f"{context} must be a list of non-empty strings")
    items: list[str] = []
    for index, item in enumerate(value):
        items.append(_require_str(item, f"{context}[{index}]"))
    return tuple(items)


def _validate_model_limits(value: object, catalog_path: Path) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    mapping = _require_mapping(value, f"model_limits in {catalog_path}")
    model_limits: dict[str, dict[str, Any]] = {}
    for model_name, model_limit in mapping.items():
        model_key = _require_str(model_name, f"model_limits key in {catalog_path}")
        config = _require_mapping(model_limit, f"model_limits.{model_key} in {catalog_path}")
        concurrency = config.get("concurrency")
        if not isinstance(concurrency, int) or isinstance(concurrency, bool) or concurrency <= 0:
            _error(f"model_limits.{model_key}.concurrency in {catalog_path} must be a positive integer")
        model_limits[model_key] = {"concurrency": concurrency}
    return model_limits


def _validate_harness_configs(value: object, catalog_path: Path) -> dict[str, HarnessConfig]:
    mapping = _require_mapping(value, f"harness_configs in {catalog_path}")
    if not mapping:
        _error(f"harness_configs in {catalog_path} must not be empty")
    harness_configs: dict[str, HarnessConfig] = {}
    for name, raw_config in mapping.items():
        config_name = _require_str(name, f"harness_configs key in {catalog_path}")
        config = _require_mapping(raw_config, f"harness_configs.{config_name} in {catalog_path}")
        harness = _require_str(config.get("harness"), f"harness_configs.{config_name}.harness in {catalog_path}")
        command = config.get("command")
        if not isinstance(command, list) or not command:
            _error(f"harness_configs.{config_name}.command in {catalog_path} must be a non-empty list")
        command_items = tuple(
            _require_str(item, f"harness_configs.{config_name}.command[{index}] in {catalog_path}")
            for index, item in enumerate(command)
        )
        harness_configs[config_name] = HarnessConfig(config_name, harness, command_items)
    return harness_configs


def _validate_role_configs(
    value: object,
    catalog_path: Path,
    harness_configs: dict[str, HarnessConfig],
) -> dict[str, RoleConfig]:
    mapping = _require_mapping(value, f"roles in {catalog_path}")
    if not mapping:
        _error(f"roles in {catalog_path} must not be empty")
    roles: dict[str, RoleConfig] = {}
    for name, raw_config in mapping.items():
        role_name = _require_str(name, f"roles key in {catalog_path}")
        config = _require_mapping(raw_config, f"roles.{role_name} in {catalog_path}")
        harness_config_value = config.get("harness_config")
        if harness_config_value is None:
            continue
        harness_config = _require_str(
            harness_config_value,
            f"roles.{role_name}.harness_config in {catalog_path}",
        )
        if harness_config not in harness_configs:
            _error(
                f"roles.{role_name}.harness_config in {catalog_path} references unknown harness_config '{harness_config}'"
            )
        env_value = config.get("env")
        env: dict[str, str] = {}
        if env_value is not None:
            env_mapping = _require_mapping(env_value, f"roles.{role_name}.env in {catalog_path}")
            for key, value in env_mapping.items():
                env_key = _require_str(key, f"roles.{role_name}.env key in {catalog_path}")
                env_value_str = _require_str(
                    value, f"roles.{role_name}.env.{env_key} in {catalog_path}"
                )
                env[env_key] = env_value_str
        roles[role_name] = RoleConfig(
            name=role_name,
            harness_config=harness_config,
            model=_optional_str(config.get("model"), f"roles.{role_name}.model in {catalog_path}"),
            profile=_optional_str(config.get("profile"), f"roles.{role_name}.profile in {catalog_path}"),
            agent=_optional_str(config.get("agent"), f"roles.{role_name}.agent in {catalog_path}"),
            env=env,
            skills=_require_str_list(config.get("skills"), f"roles.{role_name}.skills in {catalog_path}"),
            enabled=True,
            prompt_addition=_optional_str(
                config.get("prompt_addition"), f"roles.{role_name}.prompt_addition in {catalog_path}"
            )
            or "",
            nested_dispatch_depth=_optional_positive_int(config.get("nested_dispatch_depth")),
            turn_limit=_optional_positive_int(config.get("turn_limit")),
            soft_timeout=_optional_positive_int(config.get("soft_timeout")),
        )
    return roles


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:  # pragma: no cover - dependency is present in the test environment
        raise RuntimeError("PyYAML is required to parse agent catalogs") from _YAML_IMPORT_ERROR
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise CatalogConfigError(f"{path} must contain a mapping at the top level")
    return data


def load_agent_catalog(catalog_path: Path | str) -> dict[str, Any]:
    path = Path(catalog_path)
    data = _load_yaml(path)
    default_role = _require_str(data.get("default_role"), f"default_role in {path}")
    harness_configs = _validate_harness_configs(data.get("harness_configs"), path)
    roles = _validate_role_configs(data.get("roles"), path, harness_configs)
    if default_role not in roles:
        _error(f"default_role '{default_role}' in {path} is not defined in roles")
    _validate_model_limits(data.get("model_limits"), path)
    return data


def load_catalog(catalog_path: Path | str) -> BenchConfig:
    path = Path(catalog_path)
    data = load_agent_catalog(path)
    harness_configs = _validate_harness_configs(data.get("harness_configs"), path)
    roles = _validate_role_configs(data.get("roles"), path, harness_configs)
    return BenchConfig(
        catalog_path=path,
        catalog_sha256=sha256(path.read_bytes()).hexdigest(),
        default_role=_require_str(data.get("default_role"), f"default_role in {path}"),
        harness_configs=harness_configs,
        roles=roles,
        model_limits=_validate_model_limits(data.get("model_limits"), path),
    )


def resolve_harness_for_role(catalog_path: Path | str, role: str | None = None) -> dict[str, object]:
    catalog = load_catalog(catalog_path)
    effective_role = role or catalog.default_role
    role_config = catalog.roles.get(effective_role)
    if role_config is None:
        raise KeyError(f"role '{effective_role}' not found in {catalog.catalog_path}")
    if not role_config.model:
        raise CatalogConfigError(
            f"role '{effective_role}' in {catalog.catalog_path} has no model"
        )
    harness_config = catalog.harness_configs[role_config.harness_config]
    return {
        "role": effective_role,
        "default_role": catalog.default_role,
        "harness_config": harness_config.name,
        "harness": harness_config.harness,
        "backend": harness_config.harness,
        "command": list(harness_config.command),
        "model": role_config.model,
        "profile": role_config.profile,
        "agent": role_config.agent,
        "env": dict(role_config.env),
        "skills": list(role_config.skills),
        "enabled": role_config.enabled,
        "catalog_path": str(catalog.catalog_path),
        "catalog_sha256": catalog.catalog_sha256,
    }


# Backwards-compatible alias for V1-style callers/tests.
def resolve_catalog_model(catalog_path: Path | str, role: str | None = None) -> dict[str, object]:
    return resolve_harness_for_role(catalog_path, role=role)
