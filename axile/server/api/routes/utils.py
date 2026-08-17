"""用于健康检查与诊断的工具路由."""

from fastapi import APIRouter

router = APIRouter(prefix="/utils", tags=["utils"])


@router.get("/health-check/")
def health_check() -> bool:
    """返回一个简单的 API 进程存活信号."""
    return True
