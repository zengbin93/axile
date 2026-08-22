"""本地交易日历查询路由。"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from axile.server.api.deps import SessionDep
from axile.server.trading_calendar import TradingCalendarEntry, list_calendar_entries

router = APIRouter(prefix="/market/trading-calendar", tags=["market"])


@router.get("", response_model=list[TradingCalendarEntry], response_model_by_alias=True)
async def get_trading_calendar(
    session: SessionDep,
    exchange: Annotated[str, Query(min_length=1)],
    start: date | None = None,
    end: date | None = None,
    only_open: Annotated[bool, Query(alias="onlyOpen")] = False,
) -> list[TradingCalendarEntry]:
    """按胜可知开放平台契约返回本地交易日历。"""
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start 必须 <= end",
        )
    return await list_calendar_entries(
        session,
        exchange=exchange,
        start=start,
        end=end,
        only_open=only_open,
    )


__all__ = ["router"]
