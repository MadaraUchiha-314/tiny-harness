"""Security invariants of the GitHub Actions workflows (issue-2 abuse cases 1-3)."""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

Workflow = dict[str, Any]


def _load(name: str) -> Workflow:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    assert isinstance(data, dict)
    raw = cast(dict[Any, Any], data)
    # PyYAML (YAML 1.1) reads the bare key `on` as the boolean True.
    if True in raw:
        raw["on"] = raw.pop(True)
    return cast(Workflow, raw)


def _jobs(workflow: Workflow) -> dict[str, Any]:
    return cast(dict[str, Any], workflow["jobs"])


def _triggers(workflow: Workflow) -> set[str]:
    on = workflow["on"]
    if isinstance(on, str):
        return {on}
    return set(cast(dict[str, Any] | list[str], on))


ALL = ["ci.yml", "release.yml", "docs.yml"]


@pytest.mark.parametrize("name", ["ci.yml", "release.yml"])
def test_workflow_defaults_to_read_only_contents(name: str) -> None:
    assert _load(name)["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("name", ALL)
def test_no_workflow_uses_pull_request_target(name: str) -> None:
    assert "pull_request_target" not in _triggers(_load(name))


def test_ci_runs_on_pull_requests_and_can_be_called() -> None:
    assert {"pull_request", "workflow_call"} <= _triggers(_load("ci.yml"))


def test_ci_never_requests_write_or_oidc() -> None:
    for job in _jobs(_load("ci.yml")).values():
        assert "permissions" not in job


def test_ci_runs_the_precommit_hooks_integration_tests_and_docs_build() -> None:
    runs = "\n".join(
        str(step.get("run", "")) for job in _jobs(_load("ci.yml")).values() for step in job["steps"]
    )
    assert "uv sync --locked" in runs
    assert "pre-commit run --all-files" in runs
    assert "pytest tests/integration" in runs
    assert "docs:build" in runs


def test_release_runs_ci_before_bumping_and_publishing() -> None:
    jobs = _jobs(_load("release.yml"))
    assert jobs["checks"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["bump"]["needs"] == "checks"
    assert jobs["publish"]["needs"] == "bump"


def test_release_triggers_on_push_to_main() -> None:
    on = _load("release.yml")["on"]
    assert on["push"]["branches"] == ["main"]


def test_only_the_bump_job_can_write_contents() -> None:
    jobs = _jobs(_load("release.yml"))
    assert jobs["bump"]["permissions"] == {"contents": "write"}
    assert "permissions" not in jobs["checks"]


def test_only_the_publish_job_gets_an_oidc_token_in_env_pypi() -> None:
    jobs = _jobs(_load("release.yml"))
    publish = jobs["publish"]
    assert publish["permissions"] == {"id-token": "write"}
    assert publish["environment"]["name"] == "pypi"
    for name, job in jobs.items():
        if name != "publish":
            assert "id-token" not in (job.get("permissions") or {})


def test_bump_skips_its_own_bump_commit() -> None:
    assert "bump:" in _jobs(_load("release.yml"))["bump"]["if"]


def test_docs_deploys_from_main_with_pages_scopes_only() -> None:
    workflow = _load("docs.yml")
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
