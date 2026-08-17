from __future__ import annotations

import locale

from axile.executor.ctp.core import openctp_compat


def test_openctp_compat_defaults_to_placeholder_mode() -> None:
    placeholder = openctp_compat.CThostFtdcReqUserLoginField(BrokerID="9999")

    assert openctp_compat.OPENCTP_AVAILABLE is False
    assert placeholder.BrokerID == "9999"


def test_ensure_valid_process_locale_uses_utf8_fallback(monkeypatch) -> None:
    calls: list[str] = []

    def fake_setlocale(_category: int, value: str | None = None) -> str:
        current_value = "" if value is None else value
        calls.append(current_value)
        if current_value == "":
            raise locale.Error("invalid locale")
        if current_value == "C.UTF-8":
            return current_value
        raise locale.Error("unsupported locale")

    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr(openctp_compat.locale, "setlocale", fake_setlocale)

    openctp_compat._ensure_valid_process_locale()

    assert calls == ["", "C.UTF-8"]
    assert openctp_compat.os.environ["LC_ALL"] == "C.UTF-8"
    assert openctp_compat.os.environ["LC_CTYPE"] == "C.UTF-8"
    assert openctp_compat.os.environ["LANG"] == "C.UTF-8"


def test_ensure_valid_process_locale_keeps_valid_locale(monkeypatch) -> None:
    calls: list[str] = []

    def fake_setlocale(_category: int, value: str | None = None) -> str:
        current_value = "" if value is None else value
        calls.append(current_value)
        return "zh_CN.UTF-8"

    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr(openctp_compat.locale, "setlocale", fake_setlocale)

    openctp_compat._ensure_valid_process_locale()

    assert calls == [""]
    assert openctp_compat.os.environ["LANG"] == "zh_CN.UTF-8"
