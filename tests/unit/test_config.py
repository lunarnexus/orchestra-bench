from __future__ import annotations

from pathlib import Path

import pytest

from bench.config import CatalogConfigError, load_agent_catalog, resolve_catalog_model, resolve_harness_for_role


V1_CATALOG = Path(__file__).resolve().parents[2] / "V1" / "config" / "orchestra" / "agent-catalog.yaml"


def test_load_agent_catalog_parses_the_v1_catalog() -> None:
    catalog = load_agent_catalog(V1_CATALOG)

    assert catalog["default_role"] == "builder"
    assert catalog["harness_configs"]["pi"]["harness"] == "pi"
    assert catalog["harness_configs"]["opencode"]["command"][0] == "opencode"
    assert catalog["roles"]["builder"]["model"]
    assert catalog["model_limits"]["lmstudio/qwen/qwen3.8-27b"]["concurrency"] == 2


def test_resolve_harness_for_role_uses_default_role_and_resolves_backend_fields(tmp_path: Path) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    catalog.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command:\n"
        "    - pi\n"
        "    - --model\n"
        "    - '{model}'\n"
        "    - -p\n"
        "    - '{prompt}'\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: example/model\n"
        "    profile: fast\n"
        "    agent: builder-agent\n"
        "    env:\n"
        "      FOO: bar\n"
        "    skills:\n"
        "    - builder\n"
        "    - reviewer\n"
    )

    resolved = resolve_harness_for_role(catalog)

    assert resolved["role"] == "builder"
    assert resolved["default_role"] == "builder"
    assert resolved["backend"] == "pi"
    assert resolved["harness"] == "pi"
    assert resolved["model"] == "example/model"
    assert resolved["profile"] == "fast"
    assert resolved["agent"] == "builder-agent"
    assert resolved["env"] == {"FOO": "bar"}
    assert resolved["skills"] == ["builder", "reviewer"]
    assert resolved["command"] == ["pi", "--model", "{model}", "-p", "{prompt}"]


def test_catalog_parser_ignores_orchestra_owned_unknown_keys(tmp_path: Path) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    catalog.write_text(
        "catalog_format: future\n"
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: ['pi', '--model', '{model}', '-p', '{prompt}']\n"
        "    runtime_hint: ignored by bench\n"
        "roles:\n"
        "  orchestrator:\n"
        "    skills:\n"
        "    - orchestrator\n"
        "    - planner\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: example/model\n"
        "    dispatch_hint: Dispatch and proceed until finished.\n"
        "model_limits:\n"
        "  example/model:\n"
        "    concurrency: 2\n"
        "    scheduling_hint: ignored by bench\n"
    )

    parsed = load_agent_catalog(catalog)
    resolved = resolve_harness_for_role(catalog)

    assert parsed["roles"]["orchestrator"]["skills"] == ["orchestrator", "planner"]
    assert resolved["role"] == "builder"
    assert resolved["model"] == "example/model"
    assert resolved["command"] == ["pi", "--model", "{model}", "-p", "{prompt}"]


def test_resolve_catalog_model_uses_explicit_role(tmp_path: Path) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    catalog.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command:\n"
        "    - pi\n"
        "    - --model\n"
        "    - '{model}'\n"
        "    - -p\n"
        "    - '{prompt}'\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: example/builder\n"
        "  reviewer:\n"
        "    harness_config: pi\n"
        "    model: example/reviewer\n"
    )

    resolved = resolve_catalog_model(catalog, role="reviewer")

    assert resolved["role"] == "reviewer"
    assert resolved["model"] == "example/reviewer"


@pytest.mark.parametrize(
    ("catalog_text", "error_type", "error_text"),
    [
        (
            "default_role: builder\n"
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command: ['pi']\n"
            "roles:\n"
            "  builder:\n"
            "    harness_config: missing\n"
            "    model: example/model\n",
            CatalogConfigError,
            "unknown harness_config",
        ),
        (
            "default_role: builder\n"
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command: ['pi']\n"
            "roles:\n"
            "  builder:\n"
            "    harness_config: pi\n"
            "    model: example/model\n",
            KeyError,
            "role 'reviewer' not found",
        ),
        (
            "default_role: builder\n"
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command: ['pi']\n"
            "roles:\n"
            "  builder:\n"
            "    harness_config: pi\n",
            CatalogConfigError,
            "has no model",
        ),
    ],
)
def test_resolve_harness_for_role_rejects_invalid_structures(
    tmp_path: Path,
    catalog_text: str,
    error_type: type[Exception],
    error_text: str,
) -> None:
    catalog = tmp_path / "agent-catalog.yaml"
    catalog.write_text(catalog_text)

    with pytest.raises(error_type, match=error_text):
        if error_type is KeyError:
            resolve_harness_for_role(catalog, role="reviewer")
        else:
            resolve_harness_for_role(catalog)
