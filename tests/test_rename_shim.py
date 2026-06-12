"""The cowork_dash → langstage rename ships a deprecated alias package."""

import sys

import pytest


def test_legacy_import_works_and_warns():
    for name in list(sys.modules):
        if name == "cowork_dash" or name.startswith("cowork_dash."):
            sys.modules.pop(name)
    with pytest.warns(DeprecationWarning, match="langstage"):
        import cowork_dash  # noqa: F401


def test_legacy_submodules_alias_the_new_ones():
    import cowork_dash.cli as old_cli
    import langstage.cli as new_cli

    assert old_cli is new_cli


def test_legacy_public_api():
    import cowork_dash

    assert hasattr(cowork_dash, "CoworkApp")
    assert cowork_dash.__version__ == "0.7.0"
