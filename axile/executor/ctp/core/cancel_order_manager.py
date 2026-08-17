"""
管理 CTP 撤单请求的生命周期.

该模块负责为撤单请求分配本地 request id，跟踪挂起请求，并在收到终态回报后
生成可复用的撤单结果对象，供后续查询或审计。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional

import loguru

from axile.executor.ctp.core.objects import CancelOrderResult, CancelOrderStatusType


@dataclass
class CancelOrderRequest:
    """撤单请求."""

    request_id: str
    order_sys_id: str = ""
    order_ref: str = ""
    exchange_id: str = ""
    instrument_id: str = ""
    status: CancelOrderStatusType = CancelOrderStatusType.PENDING
    error_code: int = 0
    error_msg: str = ""


class CancelOrderManager:
    """
    跟踪撤单请求状态，并缓存终态结果.

    Notes
    -----
    同一个 request id 在任意时刻只会存在于挂起表或结果表之一，避免并发回调
    既看到“仍在处理中”又看到“已经完成”的矛盾状态。
    """

    def __init__(self, logger: loguru.Logger | None = None) -> None:
        """
        初始化撤单状态管理器.

        Parameters
        ----------
        logger : loguru.Logger | None, optional
            日志记录器；为 ``None`` 时使用 ``loguru.logger``。
        """
        self._logger = logger or loguru.logger
        self._pending_requests: Dict[str, CancelOrderRequest] = {}
        self._results: Dict[str, CancelOrderResult] = {}
        self._lock = threading.Lock()
        self._request_counter = 0

    def create_request(
        self,
        order_sys_id: str = "",
        order_ref: str = "",
        exchange_id: str = "",
        instrument_id: str = "",
    ) -> CancelOrderRequest:
        """
        创建新的撤单请求.

        Parameters
        ----------
        order_sys_id : str, default=""
            系统订单编号。
        order_ref : str, default=""
            订单引用。
        exchange_id : str, default=""
            交易所代码。
        instrument_id : str, default=""
            合约代码。

        Returns
        -------
        CancelOrderRequest
            新创建的撤单请求。
        """
        with self._lock:
            self._request_counter += 1
            request_id = str(self._request_counter)

            request = CancelOrderRequest(
                request_id=request_id,
                order_sys_id=order_sys_id,
                order_ref=order_ref,
                exchange_id=exchange_id,
                instrument_id=instrument_id,
                status=CancelOrderStatusType.PENDING,
            )

            self._pending_requests[request_id] = request
            self._logger.debug(f"📋 创建撤单请求: {request_id} - {instrument_id}")

            return request

    def find_request(
        self,
        order_sys_id: str = "",
        order_ref: str = "",
    ) -> Optional[tuple[str, CancelOrderRequest]]:
        """
        根据订单信息查找撤单请求.

        Parameters
        ----------
        order_sys_id : str, default=""
            系统订单编号。
        order_ref : str, default=""
            订单引用。

        Returns
        -------
        Optional[tuple[str, CancelOrderRequest]]
            匹配到时返回 ``(request_id, request)``，否则返回 ``None``。
        """
        with self._lock:
            for request_id, request in self._pending_requests.items():
                if order_sys_id and request.order_sys_id == order_sys_id:
                    return request_id, request
                if order_ref and request.order_ref == order_ref:
                    return request_id, request
            return None

    def update_status(
        self,
        request_id: str,
        status: CancelOrderStatusType,
        error_code: int = 0,
        error_msg: str = "",
    ) -> Optional[CancelOrderResult]:
        """
        更新撤单请求状态并生成结果.

        Parameters
        ----------
        request_id : str
            请求 ID。
        status : CancelOrderStatusType
            新状态。
        error_code : int, default=0
            错误代码。
        error_msg : str, default=""
            错误消息。

        Returns
        -------
        Optional[CancelOrderResult]
            撤单结果；若请求不存在则返回 ``None``。
        """
        with self._lock:
            request = self._pending_requests.get(request_id)
            if not request:
                return None

            request.status = status
            request.error_code = error_code
            request.error_msg = error_msg

            result = CancelOrderResult(
                request_id=request_id,
                order_sys_id=request.order_sys_id,
                order_ref=request.order_ref,
                exchange_id=request.exchange_id,
                instrument_id=request.instrument_id,
                status=status,
                success=(status == CancelOrderStatusType.SUCCESS),
                error_code=error_code,
                error_msg=error_msg,
            )

            # 终态结果与挂起表迁移在同一个锁内完成，避免重复消费同一撤单请求。
            self._results[request_id] = result
            del self._pending_requests[request_id]

            status_desc = status.value if hasattr(status, "value") else str(status)
            self._logger.debug(f"📋 撤单请求 {request.instrument_id} 状态更新: {status_desc}")

            return result

    def get_result(self, request_id: str) -> Optional[CancelOrderResult]:
        """
        获取撤单结果.

        Parameters
        ----------
        request_id : str
            请求 ID。

        Returns
        -------
        Optional[CancelOrderResult]
            对应的撤单结果。
        """
        with self._lock:
            return self._results.get(request_id)

    def get_pending_count(self) -> int:
        """获取待处理的撤单请求数量."""
        with self._lock:
            return len(self._pending_requests)

    def get_result_count(self) -> int:
        """获取已完成的撤单结果数量."""
        with self._lock:
            return len(self._results)

    def clear(self) -> None:
        """清空所有请求和结果."""
        with self._lock:
            self._pending_requests.clear()
            self._results.clear()
            self._request_counter = 0
            self._logger.debug("✅ 已清空所有撤单请求和结果")

    def clear_old_results(self, keep_count: int = 100) -> int:
        """
        清理旧的撤单结果，保留最近的结果.

        Parameters
        ----------
        keep_count : int, default=100
            需要保留的结果数量。

        Returns
        -------
        int
            被清理的结果数量。
        """
        with self._lock:
            if len(self._results) <= keep_count:
                return 0

            # request_id 由本地单调计数器生成，因此可以直接作为“最新结果”排序依据。
            sorted_ids = sorted(self._results.keys(), key=int, reverse=True)
            ids_to_remove = sorted_ids[keep_count:]

            for request_id in ids_to_remove:
                del self._results[request_id]

            self._logger.debug(f"✅ 清理了 {len(ids_to_remove)} 个旧的撤单结果")
            return len(ids_to_remove)
