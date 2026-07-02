"""
Tests for the East Asia translate CLI flags: --kanbun, --simplified, --traditional.

These tests require both the base translation plugin and this plugin to be
installed (plugin.py present in both plugins/translation/ and
plugins/translation-ea/), since the flags are only registered on the shared
'translate' parser once both are merged into a DispatchPlugin.
"""

from pathlib import Path

import pytest

from src.cli import create_argument_parser
from src.runtime.plugin_loader import load_plugins

_PLUGINS_DIR = Path(__file__).resolve().parents[2]


def _make_parser():
    return create_argument_parser(load_plugins(_PLUGINS_DIR))


# ---------------------------------------------------------------------------
# --kanbun
# ---------------------------------------------------------------------------

class TestKanbunFlag:

    @pytest.fixture
    def parser(self):
        return _make_parser()

    def test_kanbun_defaults_to_false(self, parser):
        args = parser.parse_args(["heller", "translate", "jp-en", "-c"])
        assert args.kanbun is False

    def test_kanbun_flag_sets_true(self, parser):
        args = parser.parse_args(["heller", "translate", "jp-en", "-c", "--kanbun"])
        assert args.kanbun is True

    def test_kanbun_available_for_all_ea_source_languages(self, parser):
        for pair in ("jp-en", "zh-en", "kr-en"):
            args = parser.parse_args(["heller", "translate", pair, "-c", "--kanbun"])
            assert args.kanbun is True


# ---------------------------------------------------------------------------
# --simplified / --traditional
# ---------------------------------------------------------------------------

class TestChineseScriptFlags:

    @pytest.fixture
    def parser(self):
        return _make_parser()

    def test_simplified_defaults_to_false(self, parser):
        args = parser.parse_args(["heller", "translate", "zh-en", "-c"])
        assert args.simplified is False

    def test_traditional_defaults_to_false(self, parser):
        args = parser.parse_args(["heller", "translate", "zh-en", "-c"])
        assert args.traditional is False

    def test_simplified_flag_sets_true(self, parser):
        args = parser.parse_args(["heller", "translate", "zh-en", "-c", "--simplified"])
        assert args.simplified is True

    def test_traditional_flag_sets_true(self, parser):
        args = parser.parse_args(["heller", "translate", "zh-en", "-c", "--traditional"])
        assert args.traditional is True

    def test_simplified_and_traditional_are_mutually_exclusive(self):
        parser = _make_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "heller", "translate", "zh-en", "-c", "--simplified", "--traditional",
            ])


# ---------------------------------------------------------------------------
# Cross-command — EA flags do not bleed into the base plugin's own commands
# ---------------------------------------------------------------------------

class TestFlagIsolation:

    @pytest.fixture
    def parser(self):
        return _make_parser()

    def test_kanbun_flag_present_even_for_english_source(self, parser):
        # The flag is added to the shared 'translate' parser regardless of
        # source language (both plugins contribute flags to the same
        # parser) — it's DispatchPlugin.run() that decides which plugin's
        # run() actually acts on it. See test_plugin_run.py for that.
        args = parser.parse_args(["heller", "translate", "en-jp", "-c", "--kanbun"])
        assert args.kanbun is True
