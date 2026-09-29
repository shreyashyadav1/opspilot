"""Fixtures for the agent API: settings on a temporary data directory, in-process fake tools."""

import pytest

from opspilot_api.settings import ApiSettings
from tests.api.support import FakeTools


@pytest.fixture
def tools() -> FakeTools:
    return FakeTools()


@pytest.fixture
def settings(tmp_path) -> ApiSettings:
    return ApiSettings(
        data_dir=tmp_path / "state",
        model="fake:playbook",
        results_dir=tmp_path / "results",
    )
