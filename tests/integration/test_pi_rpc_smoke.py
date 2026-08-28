from __future__ import annotations

import os
import shutil

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BENCH_RUN_DOCKER") != "1",
    reason="set BENCH_RUN_DOCKER=1 to enable the Pi RPC smoke test",
)


def test_pi_rpc_smoke_requires_docker() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker unavailable")
    pytest.skip("real Pi RPC smoke not available in this workspace")
