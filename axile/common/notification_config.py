"""账户与系统通知函数的共同配置校验。"""

from axile.common.notification_function import validate_notification_function


def validate_notification_config(mode: str, code: str | None) -> None:
    """校验系统级通知配置；账户通知直接校验唯一函数。"""
    if mode not in {"default", "function"}:
        raise ValueError("通知模式必须为 default 或 function")
    if mode == "function":
        validate_notification_function(code or "")
