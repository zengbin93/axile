"""``_downsample_series`` 权益迷你线保极值降采样的单元测试.

锁定「保峰谷、含首末端点、点数约束、短序列原样返回」的口径，保证 Hero/舰队卡迷你线
与「回看·绩效」大图同形，且尖峰/深谷不被抽点跳过。
"""

from axile.server.api.routes.account_crud import _downsample_series


def test_shorter_than_target_returns_as_is() -> None:
    """长度不超过目标时原样返回（同一列表对象）。"""
    vals = [1.0, 2.0, 3.0]
    assert _downsample_series(vals, 60) is vals


def test_equal_to_target_returns_as_is() -> None:
    """恰好等于目标点数时不降采样。"""
    vals = [float(i) for i in range(60)]
    assert _downsample_series(vals, 60) == vals


def test_downsamples_within_target_length() -> None:
    """长序列降到不超过 target 点。"""
    vals = [float(i) for i in range(1000)]
    out = _downsample_series(vals, 60)
    assert len(out) <= 60


def test_preserves_endpoints() -> None:
    """首末端点必须保留，保证右端与当前权益一致、左端为窗口起点。"""
    vals = [float(i) for i in range(1000)]
    out = _downsample_series(vals, 60)
    assert out[0] == vals[0]
    assert out[-1] == vals[-1]


def test_preserves_sharp_peak() -> None:
    """中段一根孤立尖峰必须保留（等距抽点会漏，保极值不漏）。"""
    vals = [1.0] * 100 + [999.0] + [1.0] * 100
    out = _downsample_series(vals, 60)
    assert max(out) == 999.0


def test_preserves_sharp_trough() -> None:
    """中段一根孤立深谷必须保留。"""
    vals = [100.0] * 100 + [-50.0] + [100.0] * 100
    out = _downsample_series(vals, 60)
    assert min(out) == -50.0


def test_monotonic_input_stays_monotonic() -> None:
    """单调输入降采样后仍单调（桶内两极值按序位排列不乱序）。"""
    vals = [float(i) for i in range(500)]
    out = _downsample_series(vals, 40)
    assert out == sorted(out)


def test_degenerate_target_returns_as_is() -> None:
    """target < 4 时不足以分桶保端点，原样返回避免退化。"""
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _downsample_series(vals, 3) == vals


def test_empty_series() -> None:
    """空序列安全返回空。"""
    assert _downsample_series([], 60) == []
