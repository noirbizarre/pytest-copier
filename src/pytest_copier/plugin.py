from __future__ import annotations

import subprocess

from dataclasses import dataclass
from functools import cached_property
from io import StringIO
from pathlib import Path
from shutil import copy, copytree
from typing import TYPE_CHECKING, Any, cast

import pytest
import yaml

from _pytest._io import TerminalWriter
from copier import Worker
from copier.main import run_copy, run_update
from plumbum import local
from pytest_dir_equal import DEFAULT_IGNORES, DiffRepr, assert_dir_equal

from .errors import CopierTaskError, RunError

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


def run(cmd: str, *args, **kwargs) -> str:
    args = [cmd, *args] if args else cmd  # type: ignore
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.STDOUT, shell=True, **kwargs
        )
    except subprocess.CalledProcessError as e:
        out = StringIO()
        tw = TerminalWriter(out)
        tw.hasmarkup = True
        tw.line(f"❌ {str(e)}\n")
        if e.output:
            prefix = tw.markup("│ ", red=True)
            tw.line("╭╼ Combined output:")
            for line in e.output.splitlines():
                tw.line(f"{prefix} {line}")
            tw.line("╰╼")
        raise RunError(out.getvalue()) from e


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
    defaults: dict[str, Any]
    monkeypatch: pytest.MonkeyPatch

    def copy(self, dst: Path, **data) -> CopierProject:
        """Copy a template given some answers"""
        __tracebackhide__ = True
        try:
            run_copy(
                str(self.template),
                dst,
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
        return CopierProject(dst, self)

    def update(self, project: Path, **data) -> CopierProject:
        """Update a template given some answers"""
        __tracebackhide__ = True
        try:
            run_update(
                project,
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
        return CopierProject(project, self)

    def context(self, **answers) -> dict[str, Any]:
        """Get the context rendered given some answers"""
        __tracebackhide__ = True
        worker = self.worker(**answers)
        worker._ask()
        env = worker.jinja_env
        data = cast(dict[str, Any], worker._render_context())
        ctx = env.context_class(env, data, "", {}, env.globals)
        return ctx.get_all()

    def worker(self, dst: Path = Path(), **answers) -> Worker:
        """Get a worker with prefilled answers"""
        return Worker(
            src_path=str(self.template),
            dst_path=dst,
            unsafe=True,
            defaults=True,
            data={**self.defaults, **answers},
        )

    def delenv(self, var: str):
        """Shortcut to monkeypatch.delenv both builtin os.environ and plumbum.local.env in Copier"""
        self.monkeypatch.delenv(var, raising=False)
        self.monkeypatch.delitem(local.env, var, raising=False)

    def setenv(self, var: str, value: str):
        """Shortcut to monkeypatch.setenv builtin os.environ and plumbum.local.env in Copier"""
        self.monkeypatch.setenv(var, value)
        self.monkeypatch.setitem(local.env, var, value)


@dataclass
class CopierProject:
    path: Path
    copier: CopierFixture

    def update(self, **data) -> CopierProject:
        return self.copier.update(self.path, **data)

    @cached_property
    def answers(self) -> dict[str, Any]:
        return self.load_answers(self.path)

    @cached_property
    def context(self) -> dict[str, Any]:
        return self.copier.context(**self.answers)

    def assert_answers(self, expected: Path):
        __tracebackhide__ = True
        expected_answers = self.load_answers(expected)
        if self.answers != expected_answers:
            out = StringIO()
            tw = TerminalWriter(out)
            tw.hasmarkup = True
            tw.line("❌ Answers are different")
            AnsersDiffRepr("Answers", self.answers, expected_answers).toterminal(tw)
            raise AssertionError(out.getvalue())
        assert self.answers == expected_answers

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

    def run(self, command: str, **kwargs) -> str:
        """Run a command in the rendered project"""
        __tracebackhide__ = True
        try:
            return run(command, cwd=self.path, **kwargs)
        except RunError as e:
            # produce a more streamlined error report
            # we explicitly raise form None to cut the inner stacktrace too
            raise RuntimeError(str(e)) from None

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
def copier(
    copier_template: Path, copier_defaults: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> CopierFixture:
    return CopierFixture(
        template=copier_template, defaults=copier_defaults, monkeypatch=monkeypatch
    )
