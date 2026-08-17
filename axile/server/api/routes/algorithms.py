"""交易算法注册表查询路由."""

from fastapi import APIRouter
from pydantic import BaseModel

from axile.executor.algorithms.core.base import AlgorithmMetadata, list_algorithms_metadata

router = APIRouter(prefix="/algorithms", tags=["algorithms"])

# 内置算法所在包前缀；据此区分内置与用户自定义算法。
_BUILTIN_MODULE_PREFIX = "axile.executor.algorithms.defaults"


class AlgorithmPublic(BaseModel):
    """
    单个已注册算法的对外元数据.

    Attributes
    ----------
    name : str
        算法名称（即账户 ``algorithm.method`` 引用的值）。
    description : str
        中文说明；自定义算法暂无说明时为空串。
    channels : list[str] | None
        支持的交易渠道值列表；``None`` 表示全渠道通用。
    slots : list[str] | None
        适用槽位（``trade`` 主交易 / ``empty`` 清仓）；``None`` 表示两槽通用，
        空列表表示两槽都不适用。
    builtin : bool
        是否为内置默认算法；``False`` 表示来自用户算法目录。
    """

    name: str
    label: str
    description: str
    default_params: dict[str, object]
    params_schema: dict[str, object]
    channels: list[str] | None
    slots: list[str] | None
    builtin: bool


def _to_public(meta: AlgorithmMetadata) -> AlgorithmPublic:
    """
    将注册表元数据转换为对外可序列化模型.

    Parameters
    ----------
    meta : AlgorithmMetadata
        注册表内的算法元数据。

    Returns
    -------
    AlgorithmPublic
        面向前端的算法元数据。
    """
    module = getattr(meta.func, "__module__", "") or ""
    return AlgorithmPublic(
        name=meta.name,
        label=meta.label,
        description=meta.description,
        default_params=meta.default_params,
        params_schema=meta.params_schema,
        channels=None if meta.channels is None else sorted(meta.channels),
        slots=None if meta.slots is None else sorted(meta.slots),
        builtin=module.startswith(_BUILTIN_MODULE_PREFIX),
    )


@router.get("", response_model=list[AlgorithmPublic])
def list_registered_algorithms() -> list[AlgorithmPublic]:
    """
    返回全部已注册算法的元数据.

    Returns
    -------
    list[AlgorithmPublic]
        按名称排序的算法元数据列表，含内置与用户自定义算法。

    Notes
    -----
    渠道与槽位过滤交由前端按当前账户上下文完成；本接口只提供结构化事实。
    """
    algorithms = [_to_public(meta) for meta in list_algorithms_metadata()]
    algorithms.sort(key=lambda a: a.name)
    return algorithms
