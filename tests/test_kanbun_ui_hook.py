"""
Tests for plugin.py's web UI composer integration: the "Use Kanbun reading
conventions" checkbox contributed to the base plugin's translate composer
via register_extension_ui_hooks()/ExtensionUiHooks (src/runtime/ui_action.py).

See docs/webui-plugin-plan.md section 10 ("Resolved, same day") for why this
is keyed by *destination* language (Japanese) rather than source, and
plugins/translation/plugin.py's TEMPLATE GUIDE step 8 for the worked example
this plugin's registration mirrors. Registered under action_id="translate" —
see ExtensionUiHooks's docstring for why action_id is part of the registry
key (transcription-ea registers its own, unrelated fields under the same
"jp"/"zh"/"kr" tokens but action_id="transcribe", so the two must not
collide).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime.plugin_loader import load_plugins
from src.runtime.ui_action import apply_extension_ui_hooks, get_extension_ui_fields

_PLUGINS_DIR = Path(__file__).resolve().parents[2]

# Loading both plugins registers the Kanbun hook as a side effect of
# importing plugins/translation-ea/plugin.py (see its "Web UI composer
# integration" section) — the same reason test_plugin_run.py loads both
# plugins up front rather than importing translation-ea/plugin.py directly.
# This also loads transcription/transcription-ea (same "plugins" directory),
# which is exactly why action_id matters here — see the module docstring.
load_plugins(_PLUGINS_DIR)


def _make_sandbox():
    sandbox = SimpleNamespace()
    sandbox.translation_service = SimpleNamespace(variant_notes=[])
    return sandbox


class TestKanbunFieldRegistration:

    def test_jp_destination_offers_a_kanbun_checkbox(self):
        fields = get_extension_ui_fields("translate", "jp")
        names = [f.name for f in fields]
        assert "kanbun" in names

    def test_kanbun_field_is_a_not_required_checkbox(self):
        fields = get_extension_ui_fields("translate", "jp")
        kanbun_field = next(f for f in fields if f.name == "kanbun")
        assert kanbun_field.kind == "checkbox"
        assert kanbun_field.required is False

    def test_other_destination_languages_get_no_kanbun_field(self):
        # Chinese and Korean are this plugin's other handled languages, but
        # the Kanbun checkbox is Japanese-destination-specific only.
        assert get_extension_ui_fields("translate", "zh") == []
        assert get_extension_ui_fields("translate", "kr") == []

    def test_english_destination_gets_no_kanbun_field(self):
        assert get_extension_ui_fields("translate", "en") == []

    def test_transcribe_action_gets_no_kanbun_field_for_jp(self):
        # Regression coverage for the action_id-collision fix: transcribe's
        # own "jp" registration (transcription-ea's vertical/spread/passes
        # fields) is a completely different field set — it must never be
        # returned when asking for translate's fields.
        names = {f.name for f in get_extension_ui_fields("transcribe", "jp")}
        assert "kanbun" not in names


class TestKanbunApply:

    def test_checked_appends_kanbun_note(self):
        sandbox = _make_sandbox()
        apply_extension_ui_hooks("translate", "jp", sandbox, {"kanbun": "true"})
        assert len(sandbox.translation_service.variant_notes) == 1
        assert "kanbun" in sandbox.translation_service.variant_notes[0].lower()

    @pytest.mark.parametrize("truthy", ["true", "1", "on", "yes", "TRUE", " On "])
    def test_various_truthy_spellings_are_accepted(self, truthy):
        sandbox = _make_sandbox()
        apply_extension_ui_hooks("translate", "jp", sandbox, {"kanbun": truthy})
        assert len(sandbox.translation_service.variant_notes) == 1

    def test_unchecked_appends_nothing(self):
        sandbox = _make_sandbox()
        apply_extension_ui_hooks("translate", "jp", sandbox, {"kanbun": "false"})
        assert sandbox.translation_service.variant_notes == []

    def test_missing_field_appends_nothing(self):
        sandbox = _make_sandbox()
        apply_extension_ui_hooks("translate", "jp", sandbox, {})
        assert sandbox.translation_service.variant_notes == []

    def test_apply_is_a_noop_for_a_different_destination_token(self):
        # "en" has no registered hooks at all, so apply_extension_ui_hooks
        # must not touch the sandbox.
        sandbox = _make_sandbox()
        apply_extension_ui_hooks("translate", "en", sandbox, {"kanbun": "true"})
        assert sandbox.translation_service.variant_notes == []

    def test_apply_is_a_noop_for_the_transcribe_action_with_the_same_token(self):
        sandbox = _make_sandbox()
        apply_extension_ui_hooks("transcribe", "jp", sandbox, {"kanbun": "true"})
        assert sandbox.translation_service.variant_notes == []


class TestKanbunNoteContent:

    def test_note_matches_the_cli_flag_s_own_kanbun_note(self):
        # The composer checkbox and the CLI's --kanbun flag should produce
        # the exact same guidance text — same constant, two entry points.
        frags = sys.modules["pu_plugin.translation_ea.fragments"]
        sandbox = _make_sandbox()
        apply_extension_ui_hooks("translate", "jp", sandbox, {"kanbun": "true"})
        assert sandbox.translation_service.variant_notes[0] == frags.KANBUN_NOTE
