"""CTP 期货品种的静态交易时段表与本地判定。

数据基线：OpenCTP ``http://dict.openctp.cn/times?types=futures``，抓取于 2026-08-25。
仅覆盖 ``ProductClass=1`` 期货；期权与未知品种查表失败即拒绝。交易所调整时段或新品种
上市时，必须更新本文件、测试并随版本发布；执行路径不进行运行时刷新或外部联网。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from axile.executor.china_futures_session import is_regular_night_session_transition


@dataclass(frozen=True)
class CtpProductSession:
    """一条已校验的 CTP 品种时段记录。"""

    exchange_id: str
    product_id: str
    segment_no: int
    time_begin: time
    time_end: time


@dataclass(frozen=True)
class CtpProductSessionDecision:
    """单个 CTP 品种的时段准入结论。"""

    allowed: bool
    reason_code: str | None = None


def _sessions(
    exchange_id: str,
    product_id: str,
    *windows: tuple[str, str],
) -> tuple[CtpProductSession, ...]:
    return tuple(
        CtpProductSession(
            exchange_id=exchange_id,
            product_id=product_id,
            segment_no=index,
            time_begin=time.fromisoformat(time_begin),
            time_end=time.fromisoformat(time_end),
        )
        for index, (time_begin, time_end) in enumerate(windows, start=1)
    )


CTP_PRODUCT_SESSIONS: dict[
    tuple[str, str],
    tuple[CtpProductSession, ...],
] = {
    ("CFFEX", "IC"): _sessions("CFFEX", "IC", ("09:30:00", "11:30:00"), ("13:00:00", "15:00:00")),
    ("CFFEX", "IF"): _sessions("CFFEX", "IF", ("09:30:00", "11:30:00"), ("13:00:00", "15:00:00")),
    ("CFFEX", "IH"): _sessions("CFFEX", "IH", ("09:30:00", "11:30:00"), ("13:00:00", "15:00:00")),
    ("CFFEX", "IM"): _sessions("CFFEX", "IM", ("09:30:00", "11:30:00"), ("13:00:00", "15:00:00")),
    ("CFFEX", "T"): _sessions("CFFEX", "T", ("09:30:00", "11:30:00"), ("13:00:00", "15:15:00")),
    ("CFFEX", "TF"): _sessions("CFFEX", "TF", ("09:30:00", "11:30:00"), ("13:00:00", "15:15:00")),
    ("CFFEX", "TL"): _sessions("CFFEX", "TL", ("09:30:00", "11:30:00"), ("13:00:00", "15:15:00")),
    ("CFFEX", "TS"): _sessions("CFFEX", "TS", ("09:30:00", "11:30:00"), ("13:00:00", "15:15:00")),
    ("CZCE", "AP"): _sessions(
        "CZCE", "AP", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "CF"): _sessions(
        "CZCE",
        "CF",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "CJ"): _sessions(
        "CZCE", "CJ", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "CY"): _sessions(
        "CZCE",
        "CY",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "FG"): _sessions(
        "CZCE",
        "FG",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "JR"): _sessions(
        "CZCE", "JR", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "LR"): _sessions(
        "CZCE", "LR", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "MA"): _sessions(
        "CZCE",
        "MA",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "OI"): _sessions(
        "CZCE",
        "OI",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "PF"): _sessions(
        "CZCE",
        "PF",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "PK"): _sessions(
        "CZCE", "PK", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "PL"): _sessions(
        "CZCE",
        "PL",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "PM"): _sessions(
        "CZCE", "PM", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "PR"): _sessions(
        "CZCE",
        "PR",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "PX"): _sessions(
        "CZCE",
        "PX",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "RI"): _sessions(
        "CZCE", "RI", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "RM"): _sessions(
        "CZCE",
        "RM",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "RS"): _sessions(
        "CZCE", "RS", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "SA"): _sessions(
        "CZCE",
        "SA",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "SF"): _sessions(
        "CZCE", "SF", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "SH"): _sessions(
        "CZCE",
        "SH",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "SM"): _sessions(
        "CZCE", "SM", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "SR"): _sessions(
        "CZCE",
        "SR",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "TA"): _sessions(
        "CZCE",
        "TA",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("CZCE", "UR"): _sessions(
        "CZCE", "UR", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "WH"): _sessions(
        "CZCE", "WH", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("CZCE", "ZC"): _sessions(
        "CZCE",
        "ZC",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "a"): _sessions(
        "DCE",
        "a",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "b"): _sessions(
        "DCE",
        "b",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "bb"): _sessions("DCE", "bb", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")),
    ("DCE", "bz"): _sessions(
        "DCE",
        "bz",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "c"): _sessions(
        "DCE",
        "c",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "cs"): _sessions(
        "DCE",
        "cs",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "eb"): _sessions(
        "DCE",
        "eb",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "eg"): _sessions(
        "DCE",
        "eg",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "fb"): _sessions("DCE", "fb", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")),
    ("DCE", "i"): _sessions(
        "DCE",
        "i",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "j"): _sessions(
        "DCE",
        "j",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "jd"): _sessions("DCE", "jd", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")),
    ("DCE", "jm"): _sessions(
        "DCE",
        "jm",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "l"): _sessions(
        "DCE",
        "l",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "l_f"): _sessions(
        "DCE",
        "l_f",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "lg"): _sessions("DCE", "lg", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")),
    ("DCE", "lh"): _sessions("DCE", "lh", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")),
    ("DCE", "m"): _sessions(
        "DCE",
        "m",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "p"): _sessions(
        "DCE",
        "p",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "pg"): _sessions(
        "DCE",
        "pg",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "pp"): _sessions(
        "DCE",
        "pp",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "pp_f"): _sessions(
        "DCE",
        "pp_f",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "rr"): _sessions(
        "DCE",
        "rr",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "v"): _sessions(
        "DCE",
        "v",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "v_f"): _sessions(
        "DCE",
        "v_f",
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("DCE", "y"): _sessions(
        "DCE",
        "y",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("GFEX", "lc"): _sessions(
        "GFEX", "lc", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("GFEX", "pd"): _sessions(
        "GFEX", "pd", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("GFEX", "ps"): _sessions(
        "GFEX", "ps", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("GFEX", "pt"): _sessions(
        "GFEX", "pt", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("GFEX", "si"): _sessions(
        "GFEX", "si", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("INE", "bc"): _sessions(
        "INE",
        "bc",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("INE", "ec"): _sessions("INE", "ec", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")),
    ("INE", "lu"): _sessions(
        "INE",
        "lu",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("INE", "nr"): _sessions(
        "INE",
        "nr",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("INE", "sc"): _sessions(
        "INE",
        "sc",
        ("21:00:00", "02:30:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "ad"): _sessions(
        "SHFE",
        "ad",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "ag"): _sessions(
        "SHFE",
        "ag",
        ("21:00:00", "02:30:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "al"): _sessions(
        "SHFE",
        "al",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "ao"): _sessions(
        "SHFE",
        "ao",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "au"): _sessions(
        "SHFE",
        "au",
        ("21:00:00", "02:30:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "br"): _sessions(
        "SHFE",
        "br",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "bu"): _sessions(
        "SHFE",
        "bu",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "cu"): _sessions(
        "SHFE",
        "cu",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "fu"): _sessions(
        "SHFE",
        "fu",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "hc"): _sessions(
        "SHFE",
        "hc",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "ni"): _sessions(
        "SHFE",
        "ni",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "op"): _sessions(
        "SHFE",
        "op",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "pb"): _sessions(
        "SHFE",
        "pb",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "rb"): _sessions(
        "SHFE",
        "rb",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "ru"): _sessions(
        "SHFE",
        "ru",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "sn"): _sessions(
        "SHFE",
        "sn",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "sp"): _sessions(
        "SHFE",
        "sp",
        ("21:00:00", "23:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "ss"): _sessions(
        "SHFE",
        "ss",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
    ("SHFE", "wr"): _sessions(
        "SHFE", "wr", ("09:00:00", "10:15:00"), ("10:30:00", "11:30:00"), ("13:30:00", "15:00:00")
    ),
    ("SHFE", "zn"): _sessions(
        "SHFE",
        "zn",
        ("21:00:00", "01:00:00"),
        ("09:00:00", "10:15:00"),
        ("10:30:00", "11:30:00"),
        ("13:30:00", "15:00:00"),
    ),
}


def get_ctp_product_sessions(
    exchange_id: str,
    product_id: str,
) -> tuple[CtpProductSession, ...]:
    """返回静态表中给定期货品种的交易时段。"""
    return CTP_PRODUCT_SESSIONS.get((exchange_id, product_id), ())


def decide_ctp_product_session(
    sessions: Sequence[CtpProductSession],
    *,
    now: datetime,
    calendar_is_open: Callable[[date], bool | None],
) -> CtpProductSessionDecision:
    """按品种时段和本地交易日历判断当前时刻是否允许报单。"""
    if not sessions:
        return CtpProductSessionDecision(False, "CTP.SESSION.NO_SESSION_TABLE")

    current_time = now.timetz().replace(tzinfo=None)
    session = next((item for item in sessions if _contains(item, current_time)), None)
    if session is None:
        return CtpProductSessionDecision(False, "CTP.SESSION.CLOSED")

    try:
        if _is_night_session(session):
            return _decide_night_session(session, now.date(), current_time, calendar_is_open)
        return _decision_from_calendar(calendar_is_open(now.date()))
    except Exception:  # noqa: BLE001 - 本地日历读错时必须拒绝 CTP 报单
        return CtpProductSessionDecision(False, "CTP.SESSION.CALENDAR_UNAVAILABLE")


def _contains(session: CtpProductSession, current_time: time) -> bool:
    if session.time_end > session.time_begin:
        return session.time_begin <= current_time < session.time_end
    return current_time >= session.time_begin or current_time < session.time_end


def _is_night_session(session: CtpProductSession) -> bool:
    return session.time_begin >= time(17) or session.time_end < session.time_begin


def _decide_night_session(
    session: CtpProductSession,
    current_day: date,
    current_time: time,
    calendar_is_open: Callable[[date], bool | None],
) -> CtpProductSessionDecision:
    session_start_day = current_day - timedelta(days=1) if current_time < time(3) else current_day
    if calendar_is_open(session_start_day) is not True:
        return _decision_from_calendar(calendar_is_open(session_start_day))

    trading_day = _next_open_day(session_start_day, calendar_is_open)
    if trading_day is None:
        return CtpProductSessionDecision(False, "CTP.SESSION.CALENDAR_UNAVAILABLE")
    if not is_regular_night_session_transition(session_start_day, trading_day):
        return CtpProductSessionDecision(False, "CTP.SESSION.CLOSED")
    return CtpProductSessionDecision(True)


def _next_open_day(session_start_day: date, calendar_is_open: Callable[[date], bool | None]) -> date | None:
    for offset in range(1, 15):
        candidate = session_start_day + timedelta(days=offset)
        state = calendar_is_open(candidate)
        if state is None:
            return None
        if state:
            return candidate
    return None


def _decision_from_calendar(is_open: bool | None) -> CtpProductSessionDecision:
    if is_open is None:
        return CtpProductSessionDecision(False, "CTP.SESSION.CALENDAR_UNAVAILABLE")
    if not is_open:
        return CtpProductSessionDecision(False, "CTP.SESSION.CLOSED")
    return CtpProductSessionDecision(True)


__all__ = [
    "CTP_PRODUCT_SESSIONS",
    "CtpProductSession",
    "CtpProductSessionDecision",
    "decide_ctp_product_session",
    "get_ctp_product_sessions",
]
