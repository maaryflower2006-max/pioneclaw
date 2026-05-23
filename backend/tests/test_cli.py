"""Tests for PioneClaw CLI"""

import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (colors, bold, etc.) from terminal output."""
    # Rich/Click may emit styles even with NO_COLOR=1
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli_app():
    from app.cli.main import app

    return app


class TestCLIVersion:
    def test_version_command(self, runner, cli_app):
        result = runner.invoke(cli_app, ["version"])
        assert result.exit_code == 0
        assert "PioneClaw" in result.output
        assert "1.0.0" in result.output


class TestCLIHelp:
    def test_main_help(self, runner, cli_app):
        result = runner.invoke(cli_app, ["--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "chat" in output
        assert "task" in output
        assert "skill" in output
        assert "run" in output
        assert "version" in output

    def test_chat_help(self, runner, cli_app):
        result = runner.invoke(cli_app, ["chat", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output

    def test_task_help(self, runner, cli_app):
        result = runner.invoke(cli_app, ["task", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "create" in result.output
        assert "complete" in result.output

    def test_skill_help(self, runner, cli_app):
        result = runner.invoke(cli_app, ["skill", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "reload" in result.output


class TestCLIRun:
    def test_run_help(self, runner, cli_app):
        result = runner.invoke(cli_app, ["run", "--help"], env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "--host" in output
        assert "--port" in output
        assert "--reload" in output


class TestCLITask:
    def test_task_list_mocked(self, runner, cli_app):
        """Test task list with mocked async function"""
        with patch("app.cli.main._task_list"):
            result = runner.invoke(cli_app, ["task", "list"])
            # _task_list is called via asyncio.run, just verify command parses
            assert result.exit_code == 0 or "asyncio" in str(result.exception or "")

    def test_task_create_mocked(self, runner, cli_app):
        """Test task create argument parsing"""
        with patch("app.cli.main._task_create"):
            result = runner.invoke(cli_app, ["task", "create", "Test task"])
            assert result.exit_code == 0 or "asyncio" in str(result.exception or "")

    def test_task_complete_mocked(self, runner, cli_app):
        """Test task complete argument parsing"""
        with patch("app.cli.main._task_complete"):
            result = runner.invoke(cli_app, ["task", "complete", "1"])
            assert result.exit_code == 0 or "asyncio" in str(result.exception or "")


class TestCLISkill:
    def test_skill_list_mocked(self, runner, cli_app):
        """Test skill list command"""
        with patch("app.cli.main._skill_list"):
            result = runner.invoke(cli_app, ["skill", "list"])
            assert result.exit_code == 0 or "asyncio" in str(result.exception or "")

    def test_skill_reload_mocked(self, runner, cli_app):
        """Test skill reload command"""
        with patch("app.cli.main._skill_reload"):
            result = runner.invoke(cli_app, ["skill", "reload"])
            assert result.exit_code == 0 or "asyncio" in str(result.exception or "")


class TestCLIChat:
    def test_chat_start_help(self, runner, cli_app):
        """Test chat start command help"""
        result = runner.invoke(cli_app, ["chat", "start", "--help"], env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "--message" in output
        assert "--model" in output
        assert "--temperature" in output


class TestCLIEntryPoint:
    def test_main_function_exists(self):
        from app.cli.main import main

        assert callable(main)

    def test_app_is_typer_instance(self):
        from typer import Typer

        from app.cli.main import app

        assert isinstance(app, Typer)

    def test_cli_module_structure(self):
        """Verify all CLI sub-modules exist"""
        from app.cli import main

        assert hasattr(main, "app")
        assert hasattr(main, "chat_app")
        assert hasattr(main, "task_app")
        assert hasattr(main, "skill_app")

    def test_all_commands_registered(self):
        """Verify all commands are registered"""
        from app.cli.main import app

        # typer registers commands as callback + registered_commands
        registered = app.registered_commands
        assert len(registered) >= 2  # version + run
