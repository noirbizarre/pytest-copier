# pytest-copier

[![CI](https://github.com/noirbizarre/pytest-copier/actions/workflows/ci.yml/badge.svg)](https://github.com/noirbizarre/pytest-copier/actions/workflows/ci.yml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/noirbizarre/pytest-copier/main.svg)](https://results.pre-commit.ci/latest/github/noirbizarre/pytest-copier/main)
[![PyPI](https://img.shields.io/pypi/v/pytest-copier)](https://pypi.org/project/pytest-copier/)
[![PyPI - License](https://img.shields.io/pypi/l/pytest-copier)](https://pypi.org/project/pytest-copier/)

A pytest plugin to help testing Copier templates

**Note:** this was a PoC and it will receive the full code and documentation very soon.

## Getting started

Install `pytest-copier`:

```shell
# pip
pip install pytest-copier
# pipenv
pipenv install pytest-copier
# PDM
pdm add pytest-copier
```

## Usage

The `copier` fixture will allow you to copy a template and run tests against it.
It also allows to just test the rendering context.
It will also clean up the generated project after the tests have been run.

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_copier import CopierFixture


@pytest.fixture(scope="session")
def copier_defaults() -> dict[str, Any]:
    return {
        "project_name": "Test project",
        "author_email": "john.doe@nowhere.com",
    }


@pytest.fixture(scope="session")
def copier_template_paths() -> Sequence[str]:
    return (
        "template",
        "extensions",
        "copier.yml",
    )


def test_rendered_project(copier: CopierFixture):
    project = copier.copy(project_name="something else")

    assert project.answers["project_name") == "something else"

    some_file = project / "some.file"
    assert some_file.exists()

    output = project.run("do something")
    assert "expected" in output


def test_default_answers_context(copier: CopierFixture):
    ctx = copier.context()

    assert ctx["project_name"] == "Test project"
    assert ctx["project_slug"] == "test-project"


def test_answers_context(copier: CopierFixture):
    ctx = copier.context(project_name="my-project")

    assert ctx["project_name"] == "my-project"
    assert ctx["author_email"] == "john.doe@nowhere.com"
```

## Contributing

Read the [dedicated contributing guidelines](./CONTRIBUTING.md).
