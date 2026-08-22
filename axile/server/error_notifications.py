"""
服务端错误通知辅助函数.

集中封装飞书错误卡片构建、外部 IP 获取与错误上报流程。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import aiohttp
import loguru

from axile.common.feishu import push_feishu_card
from axile.server.db.models import Account


def build_error_card(
    err: str,
    account_name: str | None = None,
    external_ip: str | None = None,
) -> dict[str, object]:
    """
    构建飞书错误通知卡片.

    Parameters
    ----------
    err : str
        需要展示的错误详情。
    account_name : str | None, optional
        当前执行对应的账户名称。
    external_ip : str | None, optional
        当前服务实例的外部 IP。

    Returns
    -------
    dict[str, object]
        可直接发送到飞书的卡片 JSON。
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info_sections = [f"**⏰ 发生时间:** {current_time}"]
    if account_name:
        info_sections.append(f"**👤 账户名称:** {account_name}")
    else:
        info_sections.append("**👤 账户名称:** 未指定")
    if external_ip:
        info_sections.append(f"**🌐 外部IP:** {external_ip}")
    else:
        info_sections.append("**🌐 外部IP:** **无法获取IP**")

    info_content = "  \n".join(info_sections)
    error_lines = err.strip().split("\n")
    error_preview = error_lines[0] if error_lines else "未知错误"
    full_error = err.strip()

    return {
        "header": {
            "title": {"tag": "plain_text", "content": "🚨 系统错误通知"},
            "template": "red",
        },
        "elements": [
            {"tag": "markdown", "content": f"📋 **基本信息**\n{info_content}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"🔴 **错误预览:**\n {error_preview}"},
            {"tag": "markdown", "content": f"📝 **详细信息**\n\n```\n{full_error}\n```"},
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "⚠️ **处理建议**\n请立即检查系统状态，确认错误原因并及时处理。\n<at id=all></at> **请关注此错误**",
            },
        ],
    }


def build_test_card() -> dict[str, object]:
    """
    构建飞书告警联通测试卡片.

    Returns
    -------
    dict[str, object]
        结构与 :func:`build_error_card` 一致（``header`` + ``markdown`` 元素），
        以便「测试推送」验证真实告警所用的同一套卡片契约；模板与文案改为中性提示，
        避免收信人误认为真实错误。

    Notes
    -----
    仅用于系统配置向导的连通性自检，不含任何错误详情。
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "header": {
            "title": {"tag": "plain_text", "content": "🔔 axile 告警联通测试"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    "若你在群里看到这张卡片，说明**执行错误告警**的飞书机器人 key 配置正确。\n\n"
                    f"**⏰ 测试时间:** {current_time}\n\n"
                    "此为 axile 系统配置向导发出的联通测试，可忽略。"
                ),
            },
        ],
    }


async def get_external_ip() -> str:
    """
    获取当前服务实例的外部 IP 地址.

    Returns
    -------
    str
        获取成功时返回 IPv4 地址；所有服务都失败时返回空字符串。
    """
    ip_services = [
        "https://ip.sb",
        "https://ifconfig.me",
        "https://ipinfo.io/ip",
        "http://myip.ipip.net",
        "http://ip.6655.com/ip.aspx",
        "https://cip.cc",
    ]
    timeout = aiohttp.ClientTimeout(total=5)

    for service in ip_services:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(service) as response:
                    if response.status != 200:
                        continue

                    ip_text = await response.text()
                    ip = ip_text.strip()
                    if service == "https://cip.cc":
                        continue
                    if service == "http://myip.ipip.net":
                        import re

                        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", ip)
                        if match:
                            ip = match.group(1)

                    if ip and "." in ip and len(ip.split(".")) == 4:
                        parts = ip.split(".")
                        if all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
                            return ip
        except asyncio.TimeoutError:
            loguru.logger.warning(f"获取外部IP超时: {service}")
        except Exception as exc:
            loguru.logger.warning(f"获取外部IP失败 {service}: {exc}")

    loguru.logger.warning("所有IP服务都无法获取外部IP地址")
    return ""


async def send_feishu_error(
    error: Exception,
    account: Account | None,
    feishu_key: str,
) -> None:
    """
    将执行异常发送到飞书.

    Parameters
    ----------
    error : Exception
        需要上报的异常对象。
    account : Account | None
        当前执行关联的账户对象。
    feishu_key : str
        飞书机器人 webhook key。
    """
    if feishu_key == "":
        return

    try:
        import traceback

        error_msg = f"{str(error)}\n\n堆栈跟踪:\n{traceback.format_exc()}"
        account_name = None if account is None else account.name
        external_ip = await get_external_ip()
        card_dict = build_error_card(error_msg, account_name, external_ip)
        await asyncio.to_thread(push_feishu_card, card_dict, feishu_key)
    except Exception as feishu_error:
        loguru.logger.error(f"发送飞书错误通知失败: {feishu_error}")
