"""
Tests for EastAsiaTranslationPlugin.run() and .get_peer_guidance() in plugin.py.

Covers the behavior that previously had no test coverage at all: Chinese
script-variant resolution (--simplified/--traditional), kanbun variant-note
injection, peer-guidance injection from DispatchPlugin, and the
requires-base-plugin guard. SandboxProcessor and the base plugin's
_execute_translate() are mocked so these tests don't need a real API key or
touch the AI model.
"""

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.errors import CLIError
from src.runtime.plugin_loader import load_plugins

_PLUGINS_DIR = Path(__file__).resolve().parents[2]

# Ensure both plugins are loaded and registered in sys.modules before any
# test runs. The plugin folder name has a hyphen ("translation-ea"), so it
# can't be imported with normal dotted syntax — the loader registers it
# under the literal string key "pu_plugin.translation-ea.plugin" instead
# (see _load_one() in src/runtime/plugin_loader.py).
load_plugins(_PLUGINS_DIR)
_ea_plugin = sys.modules["pu_plugin.translation-ea.plugin"].plugin
_base_module = sys.modules["pu_plugin.translation.plugin"]


def _make_sandbox():
    """A bare object standing in for SandboxProcessor, with a real list for variant_notes."""
    sandbox = MagicMock()
    sandbox.translation_service = SimpleNamespace(variant_notes=[])
    return sandbox


def _make_args(language_code, **extra):
    defaults = dict(kanbun=False, simplified=False, traditional=False)
    defaults.update(extra)
    return argparse.Namespace(language_code=language_code, **defaults)


@pytest.fixture
def patched_run(monkeypatch):
    """Patch SandboxProcessor construction and the base plugin's _execute_translate,
    returning (sandbox, execute_translate_mock) so a test can inspect both.
    """
    sandbox = _make_sandbox()
    monkeypatch.setattr(
        "src.runtime.sandbox_processor.SandboxProcessor",
        MagicMock(return_value=sandbox),
    )
    execute_translate = MagicMock()
    monkeypatch.setattr(_base_module, "_execute_translate", execute_translate)
    return sandbox, execute_translate


# ---------------------------------------------------------------------------
# Chinese script-variant resolution
# ---------------------------------------------------------------------------

class TestChineseScriptResolution:

    def test_no_flag_keeps_generic_chinese(self, patched_run):
        sandbox, execute_translate = patched_run
        args = _make_args(("zh", "en"))
        _ea_plugin.run(args, "heller", None, None, None, None)
        _, _, source_language, target_language = execute_translate.call_args[0]
        assert source_language == "Chinese"
        assert target_language == "English"

    def test_simplified_flag_resolves_to_simplified_chinese(self, patched_run):
        sandbox, execute_translate = patched_run
        args = _make_args(("zh", "en"), simplified=True)
        _ea_plugin.run(args, "heller", None, None, None, None)
        _, _, source_language, _ = execute_translate.call_args[0]
        assert source_language == "Simplified Chinese"

    def test_traditional_flag_resolves_to_traditional_chinese(self, patched_run):
        sandbox, execute_translate = patched_run
        args = _make_args(("zh", "en"), traditional=True)
        _ea_plugin.run(args, "heller", None, None, None, None)
        _, _, source_language, _ = execute_translate.call_args[0]
        assert source_language == "Traditional Chinese"

    def test_simplified_with_non_zh_source_raises_cli_error(self, patched_run):
        args = _make_args(("jp", "en"), simplified=True)
        with pytest.raises(CLIError, match="only valid when the source language is zh"):
            _ea_plugin.run(args, "heller", None, None, None, None)

    def test_traditional_with_non_zh_source_raises_cli_error(self, patched_run):
        args = _make_args(("jp", "en"), traditional=True)
        with pytest.raises(CLIError, match="only valid when the source language is zh"):
            _ea_plugin.run(args, "heller", None, None, None, None)


# ---------------------------------------------------------------------------
# Kanbun and peer-guidance variant notes
# ---------------------------------------------------------------------------

class TestVariantNotes:

    def test_kanbun_flag_appends_kanbun_note(self, patched_run):
        sandbox, _ = patched_run
        args = _make_args(("jp", "en"), kanbun=True)
        _ea_plugin.run(args, "heller", None, None, None, None)
        assert len(sandbox.translation_service.variant_notes) == 1
        assert "kanbun" in sandbox.translation_service.variant_notes[0].lower()

    def test_no_kanbun_flag_appends_nothing(self, patched_run):
        sandbox, _ = patched_run
        args = _make_args(("jp", "en"))
        _ea_plugin.run(args, "heller", None, None, None, None)
        assert sandbox.translation_service.variant_notes == []

    def test_peer_guidance_notes_are_appended(self, patched_run):
        sandbox, _ = patched_run
        args = _make_args(("jp", "en"), _peer_guidance=["some destination guidance"])
        _ea_plugin.run(args, "heller", None, None, None, None)
        assert "some destination guidance" in sandbox.translation_service.variant_notes

    def test_kanbun_and_peer_guidance_both_appended_in_order(self, patched_run):
        sandbox, _ = patched_run
        args = _make_args(("jp", "en"), kanbun=True, _peer_guidance=["dest note"])
        _ea_plugin.run(args, "heller", None, None, None, None)
        notes = sandbox.translation_service.variant_notes
        assert len(notes) == 2
        assert "kanbun" in notes[0].lower()
        assert notes[1] == "dest note"


# ---------------------------------------------------------------------------
# Requires-base-plugin guard and malformed language_code
# ---------------------------------------------------------------------------

class TestRunGuards:

    def test_raises_when_base_plugin_not_loaded(self, monkeypatch, patched_run):
        monkeypatch.delitem(sys.modules, "pu_plugin.translation.plugin", raising=False)
        args = _make_args(("jp", "en"))
        with pytest.raises(CLIError, match="requires the base translation plugin"):
            _ea_plugin.run(args, "heller", None, None, None, None)

    def test_raises_on_non_pair_language_code(self, patched_run):
        args = _make_args("jp")  # single code, not a (source, target) tuple
        with pytest.raises(CLIError, match="requires a language pair"):
            _ea_plugin.run(args, "heller", None, None, None, None)


# ---------------------------------------------------------------------------
# get_peer_guidance()
# ---------------------------------------------------------------------------

class TestGetPeerGuidance:

    def test_returns_none_for_unregistered_token(self):
        assert _ea_plugin.get_peer_guidance("jp") is None

    def test_returns_registered_guidance(self, monkeypatch):
        frags = sys.modules["pu_plugin.translation_ea.fragments"]
        monkeypatch.setitem(frags.PEER_GUIDANCE, "jp", "use natural sentence-final forms")
        assert _ea_plugin.get_peer_guidance("jp") == "use natural sentence-final forms"
