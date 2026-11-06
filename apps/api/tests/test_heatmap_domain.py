"""Hour x weekday grid of alerts and median wait (pure, no DB)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aivee_api.alerts.domain import Lifecycle, wait_heatmap

BUCHAREST = ZoneInfo("Europe/Bucharest")


def life(opened: datetime, wait_s: float | None) -> Lifecycle:
    if wait_s is None:
        return Lifecycle(opened_at=opened)
    return Lifecycle(opened_at=opened, arrived_at=opened + timedelta(seconds=wait_s))


def test_empty_grid_is_7_by_24_zeros() -> None:
    grid = wait_heatmap([], BUCHAREST)
    assert len(grid) == 7 and all(len(row) == 24 for row in grid)
    assert all(c.alerts == 0 and c.wait_median_s is None for row in grid for c in row)


def test_cells_use_the_local_hour_and_weekday() -> None:
    # Tuesday 2026-11-03 18:10 UTC is 20:10 in Bucharest (EET, UTC+2).
    tue = datetime(2026, 11, 3, 18, 10, tzinfo=UTC)
    grid = wait_heatmap(
        [life(tue, 100), life(tue + timedelta(minutes=5), 120), life(tue, 140), life(tue, None)],
        BUCHAREST,
    )
    cell = grid[1][20]  # Monday = 0
    assert cell.alerts == 4 and cell.wait_median_s == 120
    assert sum(c.alerts for row in grid for c in row) == 4


def test_late_utc_evening_rolls_over_to_the_next_local_day() -> None:
    # Sunday 23:30 UTC is Monday 01:30 in Bucharest.
    sun = datetime(2026, 11, 8, 23, 30, tzinfo=UTC)
    grid = wait_heatmap([life(sun, 60)], BUCHAREST)
    assert grid[0][1].alerts == 1 and grid[6][23].alerts == 0


def test_summer_time_shifts_by_three_hours() -> None:
    july = datetime(2026, 7, 7, 9, 0, tzinfo=UTC)  # a Tuesday, EEST (UTC+3)
    assert wait_heatmap([life(july, 30)], BUCHAREST)[1][12].alerts == 1
