"""开放交易渠道标识类型测试。"""

from pydantic import BaseModel

from axile.common.trade_channel import TradeChannel


class _ChannelPayload(BaseModel):
    channel: TradeChannel


def test_trade_channel_accepts_unknown_string_and_serializes_as_string() -> None:
    payload = _ChannelPayload.model_validate({"channel": "vendor-demo"})

    assert payload.channel == "vendor-demo"
    assert payload.channel.value == "vendor-demo"
    assert payload.model_dump(mode="json") == {"channel": "vendor-demo"}


def test_trade_channel_json_schema_is_open_string() -> None:
    schema = _ChannelPayload.model_json_schema()["properties"]["channel"]

    assert schema["type"] == "string"
    assert "enum" not in schema


def test_builtin_channel_constants_remain_string_compatible() -> None:
    assert TradeChannel.CTP == "ctp"
    assert TradeChannel.QMT == "qmt"
    assert TradeChannel.GM == "gm"
