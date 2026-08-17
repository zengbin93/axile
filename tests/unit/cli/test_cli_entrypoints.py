from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from typer.testing import CliRunner

from axile.cli import server as cli_server

cli_main = importlib.import_module("axile.cli.main")

runner = CliRunner()


def test_main_callback_runs_server_when_no_subcommand(monkeypatch) -> None:
    calls: dict[str, object] = {}

    fake_server_main = ModuleType("axile.server.main")

    def fake_run_server(**kwargs: object) -> None:
        calls.update(kwargs)

    fake_server_main.run_server = fake_run_server  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "axile.server.main", fake_server_main)

    result = runner.invoke(
        cli_main.app,
        [
            "--host",
            "127.0.0.1",
            "--port",
            "9000",
            "--algorithm-dir",
            "algos",
            "--workers",
            "2",
            "--reload",
            "--reload-dir",
            "axile",
            "--reload-dir",
            "user_algorithms",
        ],
    )

    assert result.exit_code == 0
    assert calls == {
        "host": "127.0.0.1",
        "port": 9000,
        "algorithm_dir": Path("algos"),
        "workers": 2,
        "reload": True,
        "reload_dirs": [Path("axile"), Path("user_algorithms")],
    }


def test_server_cli_main_parses_args_and_converts_paths(monkeypatch) -> None:
    parsed_args = SimpleNamespace(
        host="127.0.0.1",
        port=9443,
        algorithm_dir="user_algorithms",
        workers=4,
        reload=False,
        reload_dir=[],
    )
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli_server, "build_arg_parser", lambda: SimpleNamespace(parse_args=lambda: parsed_args))
    monkeypatch.setattr(cli_server, "run_server", lambda **kwargs: calls.update(kwargs))

    cli_server.main()

    assert calls == {
        "host": "127.0.0.1",
        "port": 9443,
        "algorithm_dir": Path("user_algorithms"),
        "workers": 4,
        "reload": False,
        "reload_dirs": [],
    }
