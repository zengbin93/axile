"""中国期货整市场可撮合窗。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from axile.executor.china_futures_session import is_within_possible_china_futures_session

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 8, 26, 20, 34, tzinfo=_SHANGHAI), False),
        (datetime(2026, 8, 26, 21, 0, tzinfo=_SHANGHAI), True),
        (datetime(2026, 8, 27, 2, 29, tzinfo=_SHANGHAI), True),
        (datetime(2026, 8, 27, 2, 30, tzinfo=_SHANGHAI), False),
        (datetime(2026, 8, 26, 9, 0, tzinfo=_SHANGHAI), True),
        (datetime(2026, 8, 26, 15, 14, tzinfo=_SHANGHAI), True),
        (datetime(2026, 8, 26, 15, 15, tzinfo=_SHANGHAI), False),
        (datetime(2026, 8, 26, 8, 59, tzinfo=_SHANGHAI), False),
    ],
)
def test_possible_china_futures_session_windows(moment: datetime, expected: bool) -> None:
    assert is_within_possible_china_futures_session(moment) is expected


def test_naive_datetime_is_treated_as_shanghai() -> None:
    assert is_within_possible_china_futures_session(datetime(2026, 8, 26, 20, 34)) is False
    assert is_within_possible_china_futures_session(datetime(2026, 8, 26, 21, 15)) is True
