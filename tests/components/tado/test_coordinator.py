"""Tests for the Tado coordinator."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
import requests_mock

from homeassistant.components.tado.coordinator import (
    HOME_DATA_INTERVAL,
    MIN_UPDATE_INTERVAL,
    SETUP_DATA_INTERVAL,
    TadoDataUpdateCoordinator,
)
from homeassistant.core import HomeAssistant

ZONE_STATES = "/api/v2/homes/1/zonestates"
HOME_DATA = {
    "/api/v2/homes/1/devices",
    "/api/v2/homes/1/weather",
    "/api/v2/homes/1/state",
}


def _coordinator(hass: HomeAssistant) -> TadoDataUpdateCoordinator:
    return hass.config_entries.async_entries("tado")[0].runtime_data


async def _refresh_paths(
    hass: HomeAssistant,
    api: requests_mock.Mocker,
    freezer: FrozenDateTimeFactory,
    after: timedelta,
) -> list[str]:
    """Move the clock on, refresh, and return the API paths that were called.

    Token renewals are left out: they are authentication, not API data calls.
    """
    api.reset_mock()
    freezer.tick(after)
    await _coordinator(hass).async_refresh()
    await hass.async_block_till_done()
    return [
        request.path
        for request in api.request_history
        if not request.path.startswith("/oauth")
    ]


async def test_refresh_fetches_only_zone_states(
    hass: HomeAssistant,
    init_integration: requests_mock.Mocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A refresh soon after the last one makes a single call for the zone states."""
    await _refresh_paths(hass, init_integration, freezer, SETUP_DATA_INTERVAL)

    paths = await _refresh_paths(hass, init_integration, freezer, timedelta(minutes=1))

    assert paths == [ZONE_STATES]


async def test_refresh_fetches_home_data_after_its_interval(
    hass: HomeAssistant,
    init_integration: requests_mock.Mocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The devices, weather and home state are fetched once they are stale."""
    await _refresh_paths(hass, init_integration, freezer, SETUP_DATA_INTERVAL)

    paths = await _refresh_paths(hass, init_integration, freezer, HOME_DATA_INTERVAL)

    assert set(paths) == HOME_DATA | {ZONE_STATES}


async def test_refresh_fetches_setup_data_after_its_interval(
    hass: HomeAssistant,
    init_integration: requests_mock.Mocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The account, zones, offsets and default overlays are fetched once stale."""
    await _refresh_paths(hass, init_integration, freezer, SETUP_DATA_INTERVAL)

    paths = await _refresh_paths(hass, init_integration, freezer, SETUP_DATA_INTERVAL)

    assert "/api/v2/me" in paths
    assert "/api/v2/homes/1/zones" in paths
    assert any(path.endswith("/temperatureoffset") for path in paths)
    assert any(path.endswith("/defaultoverlay") for path in paths)
    assert HOME_DATA | {ZONE_STATES} <= set(paths)


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        # Plenty of calls: the one-minute floor applies.
        ("20000", MIN_UPDATE_INTERVAL),
        # Few calls left: refreshes are spread out until the reset.
        ("50", None),
    ],
)
async def test_update_interval(
    hass: HomeAssistant,
    init_integration: requests_mock.Mocker,
    freezer: FrozenDateTimeFactory,
    remaining: str,
    expected: timedelta | None,
) -> None:
    """The interval spreads the remaining calls until the daily reset."""
    freezer.move_to("2026-01-15 13:00:00+01:00")
    coordinator = _coordinator(hass)
    coordinator.data["rate_limit"] = {"remaining": remaining}

    coordinator._calculate_update_interval()

    if expected is not None:
        assert coordinator.update_interval == expected
    else:
        assert coordinator.update_interval > timedelta(hours=1)
