# -*- coding: utf-8 -*-
"""
CTP临时文件清理工具.

OpenCTP会自动生成一些临时文件（如*.con），这个模块提供清理功能
"""

import os
import re
import shutil
from typing import List, Optional

import loguru


class CtpTempCleaner:
    """CTP临时文件清理器."""

    def __init__(self) -> None:
        self.temp_paths: List[str] = []
        self.project_root: Optional[str] = None

    def register_temp_path(self, path: str) -> None:
        """注册临时路径."""
        if path not in self.temp_paths:
            self.temp_paths.append(path)

    def register_project_root(self, root_path: str) -> None:
        """注册项目根目录."""
        self.project_root = root_path

    def clean_project_temp_files(self, extensions: Optional[List[str]] = None) -> int:
        """
        清理项目根目录下的临时文件.

        Parameters
        ----------
        extensions : Optional[List[str]], optional
            要清理的文件扩展名列表；未提供时默认清理 ``[".con", ".log"]``。

        Returns
        -------
        int
            清理的文件数量。
        """
        if not self.project_root or not os.path.exists(self.project_root):
            return 0

        if extensions is None:
            extensions = [".con", ".log"]

        cleaned_count = 0

        try:
            for file_name in os.listdir(self.project_root):
                file_path = os.path.join(self.project_root, file_name)

                # 跳过目录
                if os.path.isdir(file_path):
                    continue

                # 检查文件扩展名
                _, ext = os.path.splitext(file_name)
                if ext.lower() in extensions:
                    try:
                        os.remove(file_path)
                        cleaned_count += 1
                        loguru.logger.debug(f"已清理临时文件: {file_name}")
                    except Exception as e:
                        loguru.logger.warning(f"清理文件失败 {file_name}: {e}")

        except Exception as e:
            loguru.logger.error(f"清理项目临时文件失败: {e}")

        if cleaned_count > 0:
            loguru.logger.info(f"🧹 清理了 {cleaned_count} 个CTP临时文件")

        return cleaned_count

    def clean_temp_directories(self) -> int:
        """
        清理注册的临时目录.

        Returns
        -------
        int
            清理的目录数量。
        """
        cleaned_count = 0

        for temp_path in self.temp_paths:
            try:
                if os.path.exists(temp_path):
                    shutil.rmtree(temp_path)
                    cleaned_count += 1
                    loguru.logger.debug(f"已清理临时目录: {temp_path}")
            except Exception as e:
                loguru.logger.warning(f"清理临时目录失败 {temp_path}: {e}")

        if cleaned_count > 0:
            loguru.logger.info(f"🧹 清理了 {cleaned_count} 个CTP临时目录")

        return cleaned_count

    def clean_all(self) -> int:
        """
        清理所有临时文件和目录.

        Returns
        -------
        int
            清理的总数量。
        """
        file_count = self.clean_project_temp_files()
        dir_count = self.clean_temp_directories()
        return file_count + dir_count


# 全局清理器实例
_global_cleaner = CtpTempCleaner()


def register_temp_path(path: str) -> None:
    """注册临时路径到全局清理器."""
    _global_cleaner.register_temp_path(path)


def register_project_root(root_path: str) -> None:
    """注册项目根目录到全局清理器."""
    _global_cleaner.register_project_root(root_path)


def clean_ctp_temp_files(project_path: Optional[str] = None) -> int:
    """
    清理CTP临时文件的便捷函数.

    Parameters
    ----------
    project_path : Optional[str], optional
        项目根目录路径；未提供时使用已注册路径。

    Returns
    -------
    int
        清理的文件数量。
    """
    if project_path:
        _global_cleaner.register_project_root(project_path)

    return _global_cleaner.clean_all()


def build_ctp_flow_path(base_dir: str, account_id: str | None, api_kind: str) -> str:
    """
    构建 CTP flow 临时目录路径.

    Parameters
    ----------
    base_dir : str
        临时目录根路径。
    account_id : str | None
        账户标识；为空时回退到 ``default``。
    api_kind : str
        API 类型，通常为 ``"trader"`` 或 ``"md"``。

    Returns
    -------
    str
        归一化后的 CTP flow 目录路径。
    """
    normalized_account_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", (account_id or "").strip()) or "default"
    normalized_api_kind = re.sub(r"[^A-Za-z0-9_.-]+", "_", api_kind.strip()) or "unknown"
    return os.path.join(base_dir, "ctp_flow", normalized_account_id, normalized_api_kind)


def auto_clean_on_exit(project_path: str) -> None:
    """
    注册程序退出时自动清理.

    Parameters
    ----------
    project_path : str
        项目根目录路径。
    """
    import atexit

    _global_cleaner.register_project_root(project_path)

    def cleanup() -> None:
        count = _global_cleaner.clean_all()
        if count > 0:
            print(f"程序退出时清理了 {count} 个CTP临时文件")

    atexit.register(cleanup)


if __name__ == "__main__":
    # 测试清理功能
    current_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    count = clean_ctp_temp_files(current_dir)
    print(f"清理了 {count} 个临时文件")
