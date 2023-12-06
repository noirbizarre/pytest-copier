from __future__ import annotations

import shlex
import subprocess

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from shutil import copy, copytree
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from _pytest._io import TerminalWriter
from copier.main import run_copy, run_update
from plumbum import local
from pytest_dir_equal import DEFAULT_IGNORES, DiffRepr, assert_dir_equal

from .errors import CopierTaskError, ProjectRunError

if TYPE_CHECKING:
    from pytest_gitconfig import GitConfig


ANSWERS_FILE = ".copier-answers.yml"


@dataclass
class AnsersDiffRepr(DiffRepr):
    expected: dict
    actual: dict

    def _as_lines(self, answers: dict) -> list[str]:
        return yaml.dump(
            {key: value for key, value in answers.items() if not key.startswith("_")},
            sort_keys=True,
        ).splitlines()

    def actual_lines(self) -> list[str]:
        return self._as_lines(self.actual)

    def expected_lines(self) -> list[str]:
        return self._as_lines(self.expected)


def run(cmd: str, *args, **kwargs) -> None:
    args = [cmd, *args] if args else shlex.split(cmd)  # type: ignore
    subprocess.check_call(args, **kwargs)


@pytest.fixture(scope="session")
def copier_template_root(request: pytest.FixtureRequest) -> Path:
    return request.config.rootpath


@pytest.fixture(scope="session")
def copier_template_paths() -> list[str]:
    return []


@pytest.fixture(scope="session", autouse=True)
def default_gitconfig(default_gitconfig: GitConfig, sessionpatch: pytest.Monkeypatch) -> GitConfig:
    """
    Use a clean and isolated default gitconfig avoiding user settings to break some tests.

    Add plumbum support to the original session-scoped fixture.
    """
    # local.env is a snapshot frozen at Python startup requiring its own monkeypatching
    for var in list(local.env.keys()):
        if var.startswith("GIT_"):
            sessionpatch.delitem(local.env, var)
    sessionpatch.setitem(local.env, "GIT_CONFIG_GLOBAL", str(default_gitconfig))
    default_gitconfig.set({"core.autocrlf": "input"})
    return default_gitconfig


@pytest.fixture(scope="session")
def copier_template(
    tmp_path_factory: pytest.TempPathFactory,
    copier_template_root: Path,
    copier_template_paths: list[str],
    default_gitconfig: GitConfig,
) -> Path:
    src = tmp_path_factory.mktemp("src", False)

    if copier_template_paths:
        for path in copier_template_paths:
            full_path = copier_template_root / path
            if full_path.is_dir():
                copytree(full_path, src / path, dirs_exist_ok=True)
            else:
                copy(full_path, src / path)
    else:
        copytree(copier_template_root, src, dirs_exist_ok=True)

    run("git", "init", cwd=src)
    run("git", "add", "-A", ".", cwd=src)
    run("git", "commit", "-m", "test", cwd=src)
    run("git", "tag", "99.99.99", cwd=src)

    return src


@dataclass
class CopierFixture:
    template: Path
    dst: Path
    defaults: dict[str, Any]

    def copy(self, **data) -> CopierProject:
        __tracebackhide__ = True
        try:
            run_copy(
                str(self.template),
                self.dst,
                overwrite=True,
                cleanup_on_error=False,
                unsafe=True,
                defaults=True,
                data={**self.defaults, **data},
            )
        except subprocess.CalledProcessError as e:
            # we catch those error which are triggered by tasks
            # we can produce a more streamlined error report
            # we explicitly raise form None to cut the inner stacktrace too
            raise CopierTaskError(f"❌ {e}") from None
        return CopierProject(self.dst)

    def update(self, **data) -> CopierProject:
        __tracebackhide__ = True
        try:
            run_update(
                str(self.template),
                self.dst,
                overwrite=True,
                cleanup_on_error=False,
                unsafe=True,
                defaults=True,
                data={**self.defaults, **data},
            )
        except subprocess.CalledProcessError as e:
            # we catch those error which are triggered by tasks
            # we can produce a more streamlined error report
            raise CopierTaskError(f"❌ {e}") from None
        return CopierProject(self.dst)


@dataclass
class CopierProject:
    path: Path

    def update(
        self,
    ):
        pass

    def assert_answers(self, expected: Path):
        __tracebackhide__ = True
        expected_answers = self.load_answers(expected)
        answers = self.load_answers(self.path)
        if answers != expected_answers:
            out = StringIO()
            tw = TerminalWriter(out)
            tw.hasmarkup = True
            tw.line("❌ Answers are different")
            AnsersDiffRepr("Answers", answers, expected_answers).toterminal(tw)
            raise AssertionError(out.getvalue())
        assert answers == expected_answers

    def load_answers(self, root: Path) -> dict[str, Any]:
        file = root / ANSWERS_FILE
        return {
            key: value
            for key, value in yaml.safe_load(file.read_text()).items()
            if not key.startswith("_")
        }

    def assert_equal(self, expected: Path, ignore: list[str] | None = None):
        __tracebackhide__ = True
        ignore = DEFAULT_IGNORES + [ANSWERS_FILE] + (ignore or [])
        assert_dir_equal(self.path, expected, ignore=ignore)

    def run(self, command: str, **kwargs):
        """Run a command in the rendered project"""
        __tracebackhide__ = True
        try:
            run(*shlex.split(command), cwd=self.path, **kwargs)
        except subprocess.CalledProcessError as e:
            # produce a more streamlined error report
            # we explicitly raise form None to cut the inner stacktrace too
            raise ProjectRunError(f"❌ {e}") from None

    def __truediv__(self, key):
        """Provide pathlib-like support"""
        try:
            return self.path.joinpath(key)
        except TypeError:
            return NotImplemented


@pytest.fixture
def copier_defaults() -> dict[str, Any]:
    return {}


@pytest.fixture
def copier(tmp_path: Path, copier_template: Path, copier_defaults: dict[str, Any]) -> CopierFixture:
    return CopierFixture(template=copier_template, dst=tmp_path / "dst", defaults=copier_defaults)
