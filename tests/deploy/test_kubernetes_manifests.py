"""Static checks of the Kubernetes manifests in deploy/kubernetes.

Schema validation runs in CI (`make k8s-check`: Kustomize render + kubeconform). These tests check
what a schema cannot: that the manifests agree with the compose stack and with what the agent and
the MCP server expect, and that an injected fault cannot be erased by the cluster itself.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
import yaml

from opspilot_agent.mcp_client import _PASSTHROUGH_PREFIXES
from opspilot_mcp.backends.live import LiveSettings
from opspilot_mcp.catalog import CATALOG

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "deploy" / "kubernetes"
KUSTOMIZATION = yaml.safe_load((K8S / "kustomization.yaml").read_text())

# Services whose fault state lives in the process: chaos can make their health endpoint fail.
FAULT_TARGETS = set(CATALOG)


def _documents() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for name in KUSTOMIZATION["resources"]:
        docs.extend(d for d in yaml.safe_load_all((K8S / name).read_text()) if d)
    return docs


DOCS = _documents()
WORKLOADS = {d["metadata"]["name"]: d for d in DOCS if d["kind"] in {"Deployment", "StatefulSet"}}
SERVICES = {d["metadata"]["name"]: d for d in DOCS if d["kind"] == "Service"}


def _pod(workload: dict[str, Any]) -> dict[str, Any]:
    return workload["spec"]["template"]


def _containers(workload: dict[str, Any]) -> list[dict[str, Any]]:
    return _pod(workload)["spec"]["containers"]


def _env(workload: dict[str, Any]) -> dict[str, str]:
    (container,) = _containers(workload)
    return {e["name"]: e["value"] for e in container.get("env", []) if "value" in e}


def _memory_mi(quantity: str) -> int:
    match = re.fullmatch(r"(\d+)(Mi|Gi)", quantity)
    assert match, f"unexpected memory quantity {quantity!r}"
    return int(match[1]) * (1024 if match[2] == "Gi" else 1)


def test_every_manifest_file_is_listed_in_the_kustomization() -> None:
    listed = set(KUSTOMIZATION["resources"]) | {"kustomization.yaml"}
    on_disk = {p.name for p in K8S.glob("*.yaml")}
    assert on_disk == listed
    for generator in KUSTOMIZATION["configMapGenerator"]:
        for entry in generator["files"]:
            assert (K8S / entry.split("=", 1)[1]).is_file()


def test_the_agent_api_pod_reads_logs_from_loki_without_the_docker_socket() -> None:
    env = _env(WORKLOADS["agent-api"])
    assert env["OPSPILOT_LOG_BACKEND"] == "loki"
    assert urlparse(env["OPSPILOT_LOKI_URL"]).hostname in SERVICES
    for doc in DOCS:
        for volume in doc.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", []):
            assert "hostPath" not in volume, doc["metadata"]["name"]


def test_the_agent_env_reaches_the_mcp_server_and_parses() -> None:
    env = _env(WORKLOADS["agent-api"])
    mcp_env = {k: v for k, v in env.items() if k.startswith(_PASSTHROUGH_PREFIXES)}
    # The MCP server is a subprocess of the API; only forwarded names reach it.
    assert {"OPSPILOT_LOG_BACKEND", "OPSPILOT_LOKI_URL", "OPSPILOT_SERVICE_URLS"} <= set(mcp_env)
    with pytest.MonkeyPatch.context() as mp:
        for key, value in mcp_env.items():
            mp.setenv(key, value)
        settings = LiveSettings.from_env()
    assert set(settings.service_urls) == set(CATALOG)
    for url in [*settings.service_urls.values(), settings.prometheus_url]:
        assert urlparse(url).hostname in SERVICES, url


def test_alloy_labels_streams_with_the_label_the_mcp_server_queries() -> None:
    config = (K8S / "config" / "config.alloy").read_text()
    label = _env(WORKLOADS["agent-api"])["OPSPILOT_LOKI_SERVICE_LABEL"]
    assert f'target_label  = "{label}"' in config
    assert "__meta_kubernetes_pod_label_app_kubernetes_io_name" in config
    # Only the investigated services are shipped, and each one is.
    shipped = {
        name
        for name, w in WORKLOADS.items()
        if _pod(w)["metadata"]["labels"].get("opspilot.dev/logs") == "true"
    }
    assert shipped == set(CATALOG)
    for name in shipped:
        assert _pod(WORKLOADS[name])["metadata"]["labels"]["app.kubernetes.io/name"] == name


def test_prometheus_scrapes_the_same_jobs_as_the_compose_stack() -> None:
    compose = yaml.safe_load((ROOT / "demo-system" / "prometheus" / "prometheus.yml").read_text())
    cluster = yaml.safe_load((K8S / "config" / "prometheus.yml").read_text())
    assert cluster == compose
    for job in cluster["scrape_configs"]:
        assert job["job_name"] in CATALOG
        for target in job["static_configs"][0]["targets"]:
            assert target.split(":")[0] in SERVICES


@pytest.mark.parametrize("name", sorted(FAULT_TARGETS))
def test_fault_targets_are_single_replica_and_probed_without_http(name: str) -> None:
    workload = WORKLOADS[name]
    assert workload["spec"]["replicas"] == 1
    (container,) = _containers(workload)
    # An outage fault answers 503 on the health endpoint. An HTTP readiness or liveness probe
    # would pull the pod from its Service or restart it, and a restart clears the fault.
    for probe in ("readinessProbe", "livenessProbe"):
        assert set(container[probe]) - {"periodSeconds", "failureThreshold"} == {"tcpSocket"}
    assert "httpGet" in container["startupProbe"]


@pytest.mark.parametrize("name", sorted(WORKLOADS))
def test_workloads_are_hardened_and_bounded(name: str) -> None:
    workload = WORKLOADS[name]
    pod = _pod(workload)["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    if name != "alloy":  # the only pod that talks to the Kubernetes API
        assert pod["automountServiceAccountToken"] is False
    for container in pod["containers"]:
        security = container["securityContext"]
        assert security["allowPrivilegeEscalation"] is False
        assert security["readOnlyRootFilesystem"] is True
        assert security["capabilities"]["drop"] == ["ALL"]
        assert "memory" in container["resources"]["requests"]
        assert "memory" in container["resources"]["limits"]
        if name != "loadgen":  # serves nothing
            assert "readinessProbe" in container


def test_services_select_a_workload_and_name_a_container_port() -> None:
    for name, service in SERVICES.items():
        selector = service["spec"]["selector"]
        matches = [
            w
            for w in WORKLOADS.values()
            if selector.items() <= _pod(w)["metadata"]["labels"].items()
        ]
        assert len(matches) == 1, name
        ports = {p["name"] for c in _containers(matches[0]) for p in c.get("ports", [])}
        for port in service["spec"]["ports"]:
            assert port["targetPort"] in ports, name


def test_the_stack_fits_a_small_kind_node() -> None:
    total = sum(
        _memory_mi(c["resources"]["limits"]["memory"])
        for w in WORKLOADS.values()
        for c in _containers(w)
    )
    # Same budget as the compose stack: a laptop with Docker capped at about 3 GB.
    assert total <= 2816, f"memory limits add up to {total} MiB"
