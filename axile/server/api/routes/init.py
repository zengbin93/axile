"""首启初始化向导相关路由.

Notes
-----
本模块提供「未完成配置」时初始化向导所需的接口：查询就绪状态、测试量化数据源
与数据库连通性、写入 ``config.toml`` 并触发重启。所有接口**均不触达业务数据库**，
因此在服务端处于初始化向导模式（数据库尚未迁移）时也能正常工作。
"""

import os
import signal
from typing import Any, Literal

import aiohttp
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from loguru import logger
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from axile.common.config import (
    CONFIG_TOML_PATH,
    SqliteDsn,
    is_configured,
    settings,
    write_config_toml,
)
from axile.server.error_notifications import build_test_card

router = APIRouter(prefix="/init", tags=["init"])

_DSN_ADAPTER: TypeAdapter[SqliteDsn] = TypeAdapter(SqliteDsn)
_QUANT_DATA_TIMEOUT_SECONDS = 15
_RESTART_DELAY_SECONDS = 0.5
# 飞书自定义机器人 webhook 前缀；测试推送走与真实告警（``czsc.fsa.push_card``）一致的地址契约。
_FEISHU_HOOK_BASE = "https://open.feishu.cn/open-apis/bot/v2/hook/"


class InitStatus(BaseModel):
    """初始化就绪状态与预填值.

    Attributes
    ----------
    configured : bool
        是否已完成初始化配置（``config.toml`` 存在）。
    data_source_available : bool
        量化数据源是否就绪（``quant_data_api`` 非空）。为 ``False`` 时前端应仅允许
        自定义组合，隐藏策略权重相关配置。
    environment : str
        当前运行环境标识。
    values : dict[str, Any]
        向导各字段的预填值（取自当前有效配置）。
    """

    configured: bool
    data_source_available: bool
    environment: str
    values: dict[str, Any]


class QuantDataTestRequest(BaseModel):
    """量化数据源连通性测试载荷."""

    token: str
    data_api: str


class DbTestRequest(BaseModel):
    """数据库连通性测试载荷."""

    uri: str


class FeishuTestRequest(BaseModel):
    """执行告警飞书机器人连通性测试载荷."""

    key: str


class TestResult(BaseModel):
    """连通性测试或保存操作的结果.

    Attributes
    ----------
    ok : bool
        是否成功。
    message : str
        面向用户的结果说明。
    """

    ok: bool
    message: str


class InitSaveRequest(BaseModel):
    """初始化向导保存载荷（对应 :class:`~axile.common.config.Settings` 的向导字段）."""

    sqlalchemy_database_uri: str
    quant_data_token: str
    quant_data_api: str
    exe_err_feishu_key: str = ""
    environment: Literal["local", "staging", "production"] = "local"
    app_log_dir: str = "./logs"
    axile_log_rotation: str = "1 day"
    algorithm_modules: list[str] = []
    algorithm_directories: list[str] = []


def _prefill_values() -> dict[str, Any]:
    """
    汇总向导各字段的预填值.

    Returns
    -------
    dict[str, Any]
        取自当前有效配置（``config.toml`` / 默认值）。

    Notes
    -----
    这里返回真实值（含量化数据 token）而不做掩码：其运行前提是本机、单用户，
    用户也需看到当前值以便确认或修改后保存。
    """
    return {
        "sqlalchemy_database_uri": str(settings.sqlalchemy_database_uri),
        "quant_data_token": settings.quant_data_token,
        "quant_data_api": settings.quant_data_api,
        "exe_err_feishu_key": settings.exe_err_feishu_key,
        "environment": settings.environment,
        "app_log_dir": str(settings.app_log_dir),
        "axile_log_rotation": settings.axile_log_rotation,
        "algorithm_modules": settings.algorithm_modules,
        "algorithm_directories": settings.algorithm_directories,
    }


@router.get("/status")
def init_status() -> InitStatus:
    """返回初始化就绪状态与向导预填值."""
    return InitStatus(
        configured=is_configured(),
        data_source_available=bool(settings.quant_data_api),
        environment=settings.environment,
        values=_prefill_values(),
    )


@router.post("/test-quant-data")
async def test_quant_data(payload: QuantDataTestRequest) -> TestResult:
    """
    测试量化数据源连通性.

    Notes
    -----
    请求形态与 :func:`axile.server.weights._fetch_latest_weights_frame` 一致
    （POST ``{api_name, token, params}``）；该数据接口不以 HTTP 状态表达失败，
    因此以「响应体是否含 ``data.items``」判定成功。测试本身的失败以 ``ok=False``
    返回（HTTP 200），便于前端统一展示 ✓/✗。
    """
    req_params = {
        "api_name": "get_latest_weights",
        "token": payload.token,
        "params": {"v": 2, "ttl": 0},
    }
    try:
        timeout = aiohttp.ClientTimeout(total=_QUANT_DATA_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(payload.data_api, json=req_params) as res:
                result = await res.json()
    except Exception as exc:  # noqa: BLE001 - 网络/解析异常统一转为失败结果
        return TestResult(ok=False, message=f"连接失败：{exc}")

    data = result.get("data") if isinstance(result, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if items is None:
        return TestResult(ok=False, message=f"响应缺少 data.items：{str(result)[:200]}")
    return TestResult(ok=True, message=f"连接成功，返回 {len(items)} 条权重记录")


@router.post("/test-db")
async def test_db(payload: DbTestRequest) -> TestResult:
    """
    测试数据库连通性.

    Notes
    -----
    用给定地址临时建立异步引擎并执行 ``SELECT 1``；无论成功与否都会释放引擎。
    对 SQLite 而言该操作可能顺带创建库文件（即目标库位置），属预期副作用。
    """
    engine = None
    try:
        engine = create_async_engine(payload.uri)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 连接异常统一转为失败结果
        return TestResult(ok=False, message=f"数据库连接失败：{exc}")
    finally:
        if engine is not None:
            await engine.dispose()
    return TestResult(ok=True, message="数据库连接成功")


@router.post("/test-feishu")
async def test_feishu(payload: FeishuTestRequest) -> TestResult:
    """
    测试执行告警飞书机器人是否连通.

    Notes
    -----
    向飞书自定义机器人 webhook 推送一张**联通测试卡片**（:func:`~axile.server.
    error_notifications.build_test_card`），走与真实执行错误告警（``send_feishu_error``
    经 ``czsc.fsa.push_card``）一致的 HTTP 契约：同一 hook 地址、``msg_type=interactive``
    信封、同构卡片，因此测试通过即代表真实告警链路可用。飞书对逻辑失败仍返回 HTTP 200，
    故以响应体 ``code == 0`` 或 ``StatusMessage == "success"`` 判定成功；测试失败以
    ``ok=False`` 返回（HTTP 200），便于前端统一展示 ✓/✗。
    """
    key = payload.key.strip()
    if not key:
        return TestResult(ok=False, message="请先填写飞书机器人 key")

    data = {"msg_type": "interactive", "card": build_test_card()}
    try:
        timeout = aiohttp.ClientTimeout(total=_QUANT_DATA_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{_FEISHU_HOOK_BASE}{key}", json=data) as res:
                result = await res.json()
    except Exception as exc:  # noqa: BLE001 - 网络/解析异常统一转为失败结果
        return TestResult(ok=False, message=f"推送失败：{exc}")

    ok = isinstance(result, dict) and (result.get("code") == 0 or result.get("StatusMessage") == "success")
    if ok:
        return TestResult(ok=True, message="测试卡片已发送，请在飞书群确认是否收到。")
    detail = (
        str(result.get("msg") or result.get("StatusMessage") or result) if isinstance(result, dict) else str(result)
    )
    return TestResult(ok=False, message=f"飞书返回失败：{detail[:200]}")


def _restart_process() -> None:
    """向自身发送 ``SIGTERM`` 触发退出，交由外部 supervisor 拉起以重读配置."""
    import time

    # 稍作延迟，确保保存响应已回发给前端后再退出。
    time.sleep(_RESTART_DELAY_SECONDS)
    logger.warning("初始化完成，进程即将退出以便重启进入正常模式。")
    os.kill(os.getpid(), signal.SIGTERM)


@router.post("/save")
def init_save(payload: InitSaveRequest, background_tasks: BackgroundTasks) -> TestResult:
    """
    校验并写入初始化配置，随后触发进程重启.

    Parameters
    ----------
    payload : InitSaveRequest
        向导收集的完整配置。
    background_tasks : BackgroundTasks
        用于在响应回发后再触发进程退出。

    Returns
    -------
    TestResult
        保存结果；成功时服务将随即退出并由 supervisor（systemd ``Restart=always``）
        拉起，重读 ``config.toml`` 进入正常模式。

    Raises
    ------
    HTTPException
        数据库地址不合法、或量化数据源 token 与接口地址只填其一时返回 422；写入文件
        失败时返回 500。
    """
    try:
        _DSN_ADAPTER.validate_python(payload.sqlalchemy_database_uri)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"数据库地址不合法：{exc}",
        ) from exc

    # 数据源为可选能力：两者同填=启用策略权重组合；两者同空=仅自定义组合模式。
    # 只填其一属半配（会得到一个取不到数的数据源），拒绝以避免静默失效。
    if bool(payload.quant_data_token.strip()) != bool(payload.quant_data_api.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="量化数据源 token 与接口地址须同时填写或同时留空；留空即以「仅自定义组合」模式运行。",
        )

    values: dict[str, Any] = {
        "sqlalchemy_database_uri": payload.sqlalchemy_database_uri,
        "quant_data_token": payload.quant_data_token,
        "quant_data_api": payload.quant_data_api,
        "exe_err_feishu_key": payload.exe_err_feishu_key,
        "environment": payload.environment,
        "app_log_dir": payload.app_log_dir,
        "axile_log_rotation": payload.axile_log_rotation,
        "algorithm_modules": payload.algorithm_modules,
        "algorithm_directories": payload.algorithm_directories,
    }
    try:
        write_config_toml(values)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写入配置文件失败：{exc}",
        ) from exc

    logger.warning("初始化配置已写入 {}，即将重启进入正常模式。", CONFIG_TOML_PATH)
    background_tasks.add_task(_restart_process)
    return TestResult(ok=True, message="配置已保存，服务正在重启……")
