"""单服务端进程内的账户运行态互斥；等待锁时不得持有数据库事务。"""

import asyncio
from weakref import WeakValueDictionary

_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


def account_runtime_lock(account_id: int) -> asyncio.Lock:
    """串行化同一账户的对齐、盘前准备与删除，空闲锁自动回收。"""
    lock = _locks.get(account_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[account_id] = lock
    return lock
