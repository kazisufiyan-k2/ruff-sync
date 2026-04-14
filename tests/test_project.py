from __future__ import annotations

import logging
import pathlib
import sys
from pprint import pformat as pf
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
import tomlkit
from packaging.version import Version
from ruamel.yaml import YAML

import ruff_sync

if TYPE_CHECKING:
    from collections.abc import Mapping

# Safe YAML parser — won't execute arbitrary Python tags in YAML files
yaml = YAML(typ="safe")

# Module-level logger for debug output during test runs
LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

# Resolves the project root by going two levels up from this test file
PROJECT_ROOT: Final = pathlib.Path(__file__).parent.parent

# Path to pyproject.toml — used to read project version
PYPROJECT_TOML: Final = PROJECT_ROOT / "pyproject.toml"

# Current Python version running the tests
PYTHON_VERSION: Final = Version(sys.version.split()[0])

# Minimum supported Python version for this project
MIN_PYTHON_VERSION: Final = Version("3.10")  # TODO: read from pyproject.toml


@pytest.fixture
def pre_commit_config_repos() -> Mapping[str, dict]:
    """
    Reads .pre-commit-config.yaml from the project root and returns a dict
    where each key is the repo URL and value contains rev + hooks info.

    Used by tests to check hook versions against other lock files.
    """
    pre_commit_config = PROJECT_ROOT / ".pre-commit-config.yaml"

    # Load YAML file as bytes to preserve encoding correctly
    yaml_dict = yaml.load(pre_commit_config.read_bytes())
    LOGGER.info(".pre-commit-config.yaml ->\n%s", pf(yaml_dict, depth=1))

    # Pop "repo" key and use it as the dict key for easy lookup by URL
    return {repo.pop("repo"): repo for repo in yaml_dict["repos"]}


@pytest.fixture
def uv_lock_packages() -> Mapping[str, dict]:
    """
    Reads uv.lock from the project root and returns a dict where each key is
    the package name and value contains version + dependency info.

    Used by tests to verify pinned versions match pre-commit hook revisions.
    """
    uv_lock = PROJECT_ROOT / "uv.lock"

    # Parse uv.lock as TOML document
    toml_doc = tomlkit.loads(uv_lock.read_text())
    LOGGER.info("uv.lock ->\n%s...", pf(toml_doc, depth=1)[:1000])

    # Unwrap tomlkit types into plain Python dicts
    packages: list[dict] = toml_doc["package"].unwrap()  # type: ignore[assignment]

    # Pop "name" key and use it as the dict key for easy lookup by package name
    return {pkg.pop("name"): pkg for pkg in packages}


def test_pre_commit_versions_are_in_sync(
    pre_commit_config_repos: Mapping[str, dict],
    uv_lock_packages: Mapping[str, dict],
) -> None:
    """
    Checks that the rev version in .pre-commit-config.yaml matches the pinned
    version in uv.lock for each mapped repo/package pair.

    This prevents ruff (or similar tools) from being updated in one place but
    not the other, which would cause different behaviour locally vs in CI.
    """
    # Maps pre-commit repo URLs to their corresponding uv.lock package names
    repo_package_lookup: dict[str, str] = {
        "https://github.com/astral-sh/ruff-pre-commit": "ruff",
    }

    for repo, package in repo_package_lookup.items():
        # Guard: ensure the repo exists in .pre-commit-config.yaml
        assert repo in pre_commit_config_repos, (
            f"Repo '{repo}' not found in .pre-commit-config.yaml"
        )

        # Guard: ensure the package exists in uv.lock
        assert package in uv_lock_packages, (
            f"Package '{package}' not found in uv.lock"
        )

        # Parse versions using packaging.Version for accurate comparison
        pre_commit_version = Version(pre_commit_config_repos[repo]["rev"])
        uv_lock_version = Version(uv_lock_packages[package]["version"])

        # Print both versions for visibility in test output
        print(f"{package} ->\n  {pre_commit_version=}\n  {uv_lock_version=}\n")

        # Fail with a clear message showing exactly which versions are out of sync
        assert pre_commit_version == uv_lock_version, (
            f"Version mismatch for '{package}':\n"
            f"  .pre-commit-config.yaml : {pre_commit_version}\n"
            f"  uv.lock                 : {uv_lock_version}\n"
            "  Keep both in sync to avoid inconsistent behaviour."
        )


def test_ruff_sync_version_is_in_sync_with_pyproject() -> None:
    """
    Checks that ruff_sync.__version__ matches the version declared in
    pyproject.toml so the package version is never accidentally out of date
    when publishing a release.
    """
    # Read and parse pyproject.toml
    toml_doc = tomlkit.loads(PYPROJECT_TOML.read_text())

    # Extract version string from [project] table
    pyproject_version: str = cast("Any", toml_doc)["project"]["version"]

    # Fail with a clear diff if the two versions do not match
    assert ruff_sync.__version__ == pyproject_version, (
        f"Version mismatch:\n"
        f"  ruff_sync.__version__ : {ruff_sync.__version__}\n"
        f"  pyproject.toml        : {pyproject_version}\n"
        "  Update one of them to keep versions in sync."
    )


# Allows running this test file directly with: python tests/test_something.py
if __name__ == "__main__":
    pytest.main([__file__, "-vv", "-rEf"])
