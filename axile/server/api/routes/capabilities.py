"""交易渠道可用性查询路由."""

from fastapi import APIRouter
from pydantic import BaseModel

from axile.channels import (
    ChannelAccountForm,
    ChannelCalendar,
    ChannelDefaults,
    ChannelLeverage,
    ChannelPortfolioPreset,
    ChannelSchedule,
    ChannelUi,
    ChannelUnits,
    list_channels,
)
from axile.server.channel_capabilities import install_extra, missing_packages

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


class ChannelCapabilityPublic(BaseModel):
    """
    单个交易渠道的依赖可用性.

    Attributes
    ----------
    channel : str
        交易渠道标识。
    available : bool
        该渠道可选依赖是否已全部安装。
    missing_packages : list[str]
        尚未安装的第三方包名；``available`` 为 ``True`` 时为空列表。
    install_extra : str
        安装该渠道依赖所用的 pyproject extra 名（``uv sync --extra <extra>``）。
    """

    channel: str
    label: str
    description: str
    icon: str
    market: str
    currency: str
    units: ChannelUnits
    ui: ChannelUi
    defaults: ChannelDefaults
    leverage: ChannelLeverage
    account_form: ChannelAccountForm
    calendar: ChannelCalendar | None
    schedule: ChannelSchedule
    portfolio: ChannelPortfolioPreset
    available: bool
    missing_packages: list[str]
    install_extra: str | None


class CalendarRequirementPublic(BaseModel):
    """当前可用渠道共同要求的一份交易日历。"""

    calendar_id: str
    label: str
    channels: list[str]
    channel_labels: list[str]
    legacy_fallback_channels: list[str]
    legacy_fallback_channel_labels: list[str]


@router.get("/channels", response_model=list[ChannelCapabilityPublic])
def list_channel_capabilities() -> list[ChannelCapabilityPublic]:
    """
    返回各交易渠道的依赖可用性.

    Returns
    -------
    list[ChannelCapabilityPublic]
        按注册表稳定顺序返回当前进程发现的全部渠道。

    Notes
    -----
    仅探测本机是否安装了对应依赖（``importlib.util.find_spec``），不判断平台支持；
    渠道名称、图标、账户表单与默认参数均由插件描述对象下发，前端按结构化数据渲染。
    """
    return [
        ChannelCapabilityPublic(
            **plugin.descriptor.model_dump(mode="python"),
            available=not (missing := missing_packages(plugin.descriptor.channel)),
            missing_packages=missing,
            install_extra=install_extra(plugin.descriptor.channel),
        )
        for plugin in list_channels()
    ]


@router.get("/calendar-requirements", response_model=list[CalendarRequirementPublic])
def list_calendar_requirements() -> list[CalendarRequirementPublic]:
    """按首次出现顺序聚合依赖完整渠道声明的交易日历。"""
    grouped: dict[str, CalendarRequirementPublic] = {}
    for plugin in list_channels():
        calendar = plugin.descriptor.calendar
        if calendar is None or missing_packages(plugin.descriptor.channel):
            continue
        item = grouped.get(calendar.calendar_id)
        if item is None:
            item = CalendarRequirementPublic(
                calendar_id=calendar.calendar_id,
                label=calendar.label,
                channels=[],
                channel_labels=[],
                legacy_fallback_channels=[],
                legacy_fallback_channel_labels=[],
            )
            grouped[calendar.calendar_id] = item
        item.channels.append(plugin.descriptor.channel)
        item.channel_labels.append(plugin.descriptor.label)
        if calendar.fallback_calendar_id is not None:
            fallback = grouped.get(calendar.fallback_calendar_id)
            if fallback is None:
                fallback = CalendarRequirementPublic(
                    calendar_id=calendar.fallback_calendar_id,
                    label=calendar.fallback_label or calendar.fallback_calendar_id,
                    channels=[],
                    channel_labels=[],
                    legacy_fallback_channels=[],
                    legacy_fallback_channel_labels=[],
                )
                grouped[calendar.fallback_calendar_id] = fallback
            fallback.legacy_fallback_channels.append(plugin.descriptor.channel)
            fallback.legacy_fallback_channel_labels.append(plugin.descriptor.label)
    return list(grouped.values())
