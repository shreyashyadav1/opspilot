import random

import pytest

from opsdemo.common.runtime import ConfigUpdate, FailureModes, ServiceRuntime


def make_runtime(seed: int = 0) -> ServiceRuntime:
    return ServiceRuntime(
        "svc", "1.0.0", {"timeout_ms": 2000, "mode": "A", "enabled": True}, rng=random.Random(seed)
    )


def test_error_rate_zero_never_fails():
    runtime = make_runtime()
    assert not any(runtime.should_fail() for _ in range(1000))


def test_error_rate_is_roughly_respected():
    runtime = make_runtime(seed=42)
    runtime.failures = FailureModes(error_rate=0.3)
    failures = sum(runtime.should_fail() for _ in range(5000))
    assert 1300 < failures < 1700


def test_added_latency_stays_within_jitter():
    runtime = make_runtime()
    runtime.failures = FailureModes(latency_ms=1000, latency_jitter_ms=100)
    samples = [runtime.added_latency_s() for _ in range(200)]
    assert all(0.9 <= s <= 1.1 for s in samples)


def test_apply_config_updates_values_and_version():
    runtime = make_runtime()
    runtime.apply_config(ConfigUpdate(version="1.0.1", values={"timeout_ms": 25}))
    assert runtime.config["timeout_ms"] == 25
    assert runtime.version == "1.0.1"


@pytest.mark.parametrize(
    "values",
    [{"unknown": 1}, {"timeout_ms": "25"}, {"timeout_ms": True}, {"enabled": 1}],
)
def test_apply_config_rejects_unknown_keys_and_wrong_types(values):
    runtime = make_runtime()
    with pytest.raises(ValueError, match=r"unknown config keys|must be of type"):
        runtime.apply_config(ConfigUpdate(values=values))
    assert runtime.config == {"timeout_ms": 2000, "mode": "A", "enabled": True}
