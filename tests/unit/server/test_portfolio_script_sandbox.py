"""自定义组合脚本子进程沙箱测试。

覆盖 issue #29：用户脚本必须在独立子进程中执行并受资源上限约束，
死循环 / 巨量分配不得拖垮承载实盘交易的服务进程。

Notes
-----
这些用例会真实 spawn 子进程（而非 mock），因为本 issue 要防的正是「协程取消
杀不掉线程」——只有真进程才能验证强杀确实生效。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import axile.server.sandbox.script_runner as script_runner
from axile.server.context import SampleContext, build_sample_context
from axile.server.sandbox import (
    CONTEXT_SCALAR_PROPERTIES,
    DEFAULT_CPU_SECONDS,
    DEFAULT_MEMORY_MB,
    DEFAULT_WALL_TIMEOUT_SECONDS,
    ContextSnapshot,
    SnapshotContext,
    run_portfolio_script,
    snapshot_context,
)

_SIMPLE_SCRIPT = "def calculate_portfolio(context):\n    return {'rb2610': 0.5}\n"


def test_simple_script_returns_target() -> None:
    """正常脚本应在子进程中跑通并回传权重。"""
    result = run_portfolio_script(_SIMPLE_SCRIPT)

    assert result.ok
    assert result.target == {"rb2610": 0.5}


def test_script_runs_in_separate_process() -> None:
    """脚本必须真的在另一个进程里执行，而非当前进程。"""
    script = "import os\ndef calculate_portfolio(context):\n    return {'pid': float(os.getpid())}\n"

    result = run_portfolio_script(script)

    assert result.ok
    assert result.target is not None
    assert result.target["pid"] != float(os.getpid()), "脚本仍在服务进程内执行，隔离未生效"


def test_infinite_loop_is_killed_and_service_survives() -> None:
    """核心验收：``while True`` 必须被终止，且不影响当前（服务）进程。

    这正是协程取消做不到的——CPython 无法强杀线程。
    """
    script = "def calculate_portfolio(context):\n    while True:\n        pass\n"

    started = time.monotonic()
    result = run_portfolio_script(script, wall_timeout=5.0, cpu_seconds=2)
    elapsed = time.monotonic() - started

    assert not result.ok
    assert result.error is not None
    assert elapsed < 15.0, f"死循环脚本未被及时终止，耗时 {elapsed:.1f}s"
    # 当前进程仍然健在，可以继续执行下一个脚本
    assert run_portfolio_script(_SIMPLE_SCRIPT).ok, "服务进程受到了影响"


def test_huge_allocation_is_capped() -> None:
    """巨量分配必须被内存上限拦住，不得 OOM 服务进程。"""
    script = (
        "def calculate_portfolio(context):\n    buf = bytearray(900 * 1024 * 1024)\n    return {'x': float(len(buf))}\n"
    )

    result = run_portfolio_script(script, memory_mb=256)

    assert not result.ok
    assert result.error is not None
    assert "MemoryError" in result.error.error_type or "ResourceLimit" in result.error.error_type
    assert run_portfolio_script(_SIMPLE_SCRIPT).ok, "服务进程受到了影响"


def test_linux_address_space_limit_remains_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux 继续使用绝对地址空间上限，不改变既有安全语义。"""
    monkeypatch.setattr(script_runner.sys, "platform", "linux")

    assert script_runner._address_space_limit_bytes(256) == 256 * 1024 * 1024


def test_darwin_address_space_limit_adds_process_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Darwin 应在既有虚拟映射基线上追加脚本预算。"""
    baseline_bytes = 400 * 1024 * 1024 * 1024
    monkeypatch.setattr(script_runner.sys, "platform", "darwin")
    monkeypatch.setattr(script_runner, "_darwin_virtual_size_bytes", lambda: baseline_bytes)

    assert script_runner._address_space_limit_bytes(256) == baseline_bytes + 256 * 1024 * 1024


def test_no_zombie_process_left() -> None:
    """超时强杀后不得残留僵尸进程。"""
    before = _zombie_count()

    run_portfolio_script(
        "def calculate_portfolio(context):\n    while True:\n        pass\n",
        wall_timeout=2.0,
        cpu_seconds=1,
    )

    assert _zombie_count() <= before, "超时强杀后残留了僵尸进程"


def _zombie_count() -> int:
    if sys.platform == "win32":  # pragma: no cover - 平台差异
        return 0
    completed = subprocess.run(
        ["bash", "-c", "ps -eo stat | grep -c '^Z' || true"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(completed.stdout.strip() or 0)


def test_syntax_error_keeps_line_and_offset() -> None:
    """语法错误必须保留行列信息——它是校验接口的核心返回字段。

    异常对象无法跨进程传递，若只回传 ``str(exc)``，行列会静默退化为 ``None``。
    """
    result = run_portfolio_script("def calculate_portfolio(context)\n    return {}\n")

    assert not result.ok
    assert result.error is not None
    assert result.error.error_type == "SyntaxError"
    assert result.error.error_line == 1
    assert result.error.error_offset is not None


def test_runtime_error_keeps_user_script_line() -> None:
    """运行时异常必须定位回用户脚本的行号，而非内部调用栈。"""
    script = "def calculate_portfolio(context):\n    raise ValueError('boom')\n"

    result = run_portfolio_script(script)

    assert not result.ok
    assert result.error is not None
    assert result.error.error_type == "ValueError"
    assert result.error.error_line == 2
    assert "boom" in result.error.error_message
    assert result.error.formatted_traceback, "应回传完整 traceback"


def test_missing_function_is_reported() -> None:
    """未定义 calculate_portfolio 应给出明确错误。"""
    result = run_portfolio_script("portfolio = {}\n")

    assert not result.ok
    assert result.error is not None
    assert "calculate_portfolio" in result.error.error_message


def test_zero_arg_signature_rejected() -> None:
    """零参旧脚本仍应被拒绝（沙箱改造不得放宽签名校验）。"""
    result = run_portfolio_script("def calculate_portfolio():\n    return {}\n")

    assert not result.ok
    assert result.error is not None
    assert "calculate_portfolio(context)" in result.error.error_message


def test_context_snapshot_is_visible_to_script() -> None:
    """脚本必须能读到上下文快照里的标量值。"""
    snapshot = snapshot_context(build_sample_context())
    script = "def calculate_portfolio(context):\n    return {'r': context.today_return}\n"

    result = run_portfolio_script(script, snapshot)

    assert result.ok
    assert result.target == {"r": build_sample_context().today_return}


def test_snapshot_covers_sample_context_fields() -> None:
    """快照字段集合必须覆盖 SampleContext 的全部字段。

    两者任一侧新增字段而另一侧遗漏时，脚本会在运行期才发现属性缺失。
    """
    sample_fields = set(vars(SampleContext()))

    assert sample_fields <= set(CONTEXT_SCALAR_PROPERTIES), (
        f"SampleContext 有快照未覆盖的字段: {sample_fields - set(CONTEXT_SCALAR_PROPERTIES)}"
    )


def test_snapshot_includes_account_id() -> None:
    """account_id 是实例属性，脚本可合法读取，快照不得漏掉。"""
    snapshot = snapshot_context(SimpleNamespace(account_id=7))

    assert snapshot is not None
    assert snapshot.values["account_id"] == 7


def test_snapshot_of_none_is_none() -> None:
    """无上下文时快照为 None，脚本收到的 context 也是 None。"""
    assert snapshot_context(None) is None

    result = run_portfolio_script("def calculate_portfolio(context):\n    return {'n': float(context is None)}\n")

    assert result.ok
    assert result.target == {"n": 1.0}


def test_property_failure_is_lazy_not_eager() -> None:
    """单个属性取值失败不应牵连未使用它的脚本（保持懒加载语义）。"""

    class _Boom:
        account_id = 1
        today_return = 0.5

        @property
        def consecutive_loss_days(self) -> int:
            raise RuntimeError("db down")

    snapshot = snapshot_context(_Boom())
    assert snapshot is not None
    assert "consecutive_loss_days" in snapshot.errors
    assert snapshot.values["today_return"] == 0.5

    # 没用到坏属性的脚本照常跑通
    ok = run_portfolio_script("def calculate_portfolio(context):\n    return {'r': context.today_return}\n", snapshot)
    assert ok.ok

    # 用到坏属性的脚本才失败
    bad = run_portfolio_script(
        "def calculate_portfolio(context):\n    return {'r': float(context.consecutive_loss_days)}\n",
        snapshot,
    )
    assert not bad.ok


def test_snapshot_context_helper_methods() -> None:
    """has_data / get_execution_count 必须随快照带过去。"""
    context = SnapshotContext(ContextSnapshot(values={}, errors={}, has_data=True, execution_count=3))

    assert context.has_data() is True
    assert context.get_execution_count() == 3


def test_snapshot_context_unknown_attribute_raises() -> None:
    """快照中不存在的属性应抛 AttributeError，语义与普通对象一致。"""
    context = SnapshotContext(ContextSnapshot())

    with pytest.raises(AttributeError):
        _ = context.definitely_not_a_field


def test_pandas_works_under_production_defaults() -> None:
    """生产默认上限下，pandas / numpy / loguru 必须可用。

    ``RLIMIT_AS`` 限制的是虚拟地址空间而非 RSS，pandas/numpy 会预留较大映射，
    默认值定得太紧会让正常脚本直接失败。
    """
    script = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "from loguru import logger\n"
        "def calculate_portfolio(context):\n"
        "    df = pd.DataFrame({'s': ['a', 'b'], 'w': np.array([0.3, 0.7])})\n"
        "    logger.info('rows=%d' % len(df))\n"
        "    return {r['s']: float(r['w']) for _, r in df.iterrows()}\n"
    )

    result = run_portfolio_script(
        script,
        wall_timeout=DEFAULT_WALL_TIMEOUT_SECONDS,
        cpu_seconds=DEFAULT_CPU_SECONDS,
        memory_mb=DEFAULT_MEMORY_MB,
    )

    assert result.ok, f"生产默认上限下 pandas 脚本失败: {result.error}"
    assert result.target == {"a": 0.3, "b": 0.7}


def test_custom_function_can_use_registered_channel_target_transform() -> None:
    """用户组合函数可显式调用渠道目标转换工具。"""
    script = (
        "import pandas as pd\n"
        "from axile.channels import get_channel\n"
        "def calculate_portfolio(context):\n"
        "    frame = pd.DataFrame([{'strategy': 'alpha', 'symbol': '600000.SH', 'weight': 0.5}])\n"
        "    target = get_channel('gm').target_transform({'alpha': 0.4}, frame)\n"
        "    return dict(zip(target['symbol'], target['contribution'], strict=True))\n"
    )

    result = run_portfolio_script(script)

    assert result.ok, f"渠道目标转换工具调用失败: {result.error}"
    assert result.target == {"600000.SH": 0.2}


def test_network_library_import_is_allowed() -> None:
    """网络库必须可 import——仓库自带示例脚本会发起网络请求。

    这也是本 PR 不做 import 白名单的直接依据。
    """
    result = run_portfolio_script("import urllib.request\ndef calculate_portfolio(context):\n    return {'net': 1.0}\n")

    assert result.ok


def test_wall_timeout_reports_timeout_error() -> None:
    """墙钟超时应给出 TimeoutError 类型，便于上层区分脚本错误与超时。"""
    script = "import time\ndef calculate_portfolio(context):\n    time.sleep(30)\n    return {}\n"

    result = run_portfolio_script(script, wall_timeout=1.0, cpu_seconds=60)

    assert not result.ok
    assert result.error is not None
    assert result.error.error_type == "TimeoutError"


def test_script_execution_error_is_value_error() -> None:
    """ScriptExecutionError 必须仍是 ValueError，保持既有调用方契约。"""
    from axile.server.sandbox import ScriptExecutionError

    assert issubclass(ScriptExecutionError, ValueError)
