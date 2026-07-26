"""PU_AISandbox East Asia Translation plugin.

Adds Japanese, Chinese, and Korean as *source* languages to the
``translate`` command the base translation plugin already provides for
English. Requires the base translation plugin (``plugins/translation/``) to
also be installed — it owns the shared translation machinery (the classes
that actually build prompts and call the AI model) that this plugin reuses
rather than duplicating.

Clone this repo into ``plugins/translation-ea/`` inside the PU_AISandbox repo.

HOW THIS PLUGIN SHARES THE ``translate`` COMMAND WITH THE BASE PLUGIN
-------------------------------------------------------------------------
This plugin declares ``handles = ["jp", "zh", "kr"]`` (the short codes a
professor types on the command line, e.g. ``jp`` for Japanese) and the base
plugin declares ``handles = ["en"]``. Because both plugins register the
same ``translate`` command, the plugin loader does not treat that as a
conflict — it notices both declare a ``handles`` list and merges them into
one ``DispatchPlugin``. At startup, the DispatchPlugin calls the base
plugin's ``register_subparsers()`` once to build the shared flags, then
calls this plugin's ``register_command_flags()`` to add the extra
East-Asia-only flags on top. When a professor actually runs a translation,
the DispatchPlugin checks which *source* language was requested and routes
to whichever plugin's ``handles`` list contains it:

  ``translate jp-en``  → this plugin owns Japanese (the source), drives the
                          translation
  ``translate en-jp``  → base plugin owns English (the source), drives the
                          translation; this plugin contributes Japanese
                          destination-side guidance (see ``get_peer_guidance()``
                          below) since Japanese is the target
  ``translate jp-fr``  → this plugin drives; a French plugin, if one were
                          installed, would contribute destination guidance;
                          with no French plugin, translation proceeds
                          without any destination-specific guidance

EA-SPECIFIC FLAGS
------------------
  ``--kanbun``
      The source text is kanbun (漢文) — Classical Chinese written for
      Japanese kundoku (訓読) reading, where small marks next to the
      characters indicate reading order and grammatical hints. This flag
      tells the model to reconstruct Japanese word order and follow
      Classical Chinese reading conventions rather than translating the
      characters in their literal written order. Appends ``KANBUN_NOTE``
      (from ``fragments.py``) to the translation service's
      ``variant_notes`` list before handing off to the base plugin's shared
      execution logic.

  ``--simplified`` / ``--traditional``
      The source Chinese text uses one specific script variety. Changes
      the resolved source language passed to the AI model from ``"Chinese"``
      to ``"Simplified Chinese"`` or ``"Traditional Chinese"``, so the model
      knows not to convert characters to the other variety. Mutually
      exclusive with each other; only valid when the source language is
      ``zh``.

FRAGMENT REGISTRATION
---------------------
At import time this plugin loads ``fragments.py``, which adds East Asia
script guidance and language-pair notes into the base plugin's shared
``translation_fragments`` module using ``dict.setdefault()`` rather than
plain assignment — so if a future language plugin ever tries to register
the same key (e.g. another plugin also providing Japanese script guidance),
whichever plugin's entry was added first is kept, and a later plugin can't
silently overwrite it.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Optional

# ── Plugin directory ──────────────────────────────────────────────────────────

_PLUGIN_DIR = Path(__file__).parent


# ── EA-internal module loader ─────────────────────────────────────────────────

def _load_ea_module(name: str, rel_path: str):
    """Load one of this plugin's own files and register it under a shared import path.

    Used once, below, to load ``fragments.py`` so ``run()`` can reference
    its constants (like ``KANBUN_NOTE``) without a plain relative import,
    keeping this plugin consistent with the ``sys.modules``-registration
    pattern the base plugin and other extension plugins use.

    Args:
        name: The dotted import path to register the module under (e.g.
              ``'pu_plugin.translation_ea.fragments'``).
        rel_path: The module's real file location, relative to this
                  plugin's own folder.

    Returns:
        The loaded module object, or ``None`` if the file doesn't exist.
    """
    if name in sys.modules:
        return sys.modules[name]
    path = _PLUGIN_DIR / rel_path
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    return None


# Load fragments and register EA data into the base plugin's fragment dicts.
# Must run at import time, after the base plugin has already injected the
# shared service modules into sys.modules (guaranteed by alphabetical load
# order: plugins/translation/ < plugins/translation-ea/).
_frags = _load_ea_module("pu_plugin.translation_ea.fragments", "fragments.py")


# ── Main-repo imports ──────────────────────────────────────────────────────────

from src.cli import add_common_flags, add_notes_flags        # noqa: E402
from src.config import parse_language_code, LANGUAGE_MAP                     # noqa: E402
from src.errors import CLIError                                # noqa: E402
from src.runtime.ui_action import UiField, register_extension_ui_hooks  # noqa: E402


# ── Web UI composer integration ────────────────────────────────────────────────
# Contributes a "Use Kanbun reading conventions" checkbox to the base
# plugin's own composer job modal — shown as a subsection once a professor
# picks Japanese as the *destination* language, the same trigger point as
# get_peer_guidance() below and the design call already recorded in
# docs/webui-plugin-plan.md section 10 ("Resolved, same day": a subsection
# appearing right after the base plugin's own options, refreshing whenever
# the destination language is picked). See ExtensionUiHooks's docstring in
# src/runtime/ui_action.py for the full mechanism this plugs into, and
# plugins/translation/plugin.py's TEMPLATE GUIDE step 8 for the worked
# example this mirrors almost exactly.
#
# Registered here at import time, independent of this plugin's own
# ``handles`` list — the composer always drives a translate job through the
# *base* plugin's ``run_ui_action`` (see ``ExtensionUiHooks``'s own
# docstring for why: ``run_ui_action`` is looked up directly off the
# primary plugin instance, never through ``DispatchPlugin``'s source-
# language routing), so this checkbox must be reachable regardless of which
# plugin would have driven the equivalent CLI command.


def _apply_kanbun_ui_hook(sandbox, fields: dict) -> None:
    """Append the kanbun/kundoku reading-convention note to this job's variant notes, if the composer's checkbox was checked.

    Called by the base translation plugin's ``run_ui_action`` via
    ``apply_extension_ui_hooks`` on every submitted translate job where
    Japanese is the destination language — a no-op (not an error) when the
    checkbox was left unchecked, the same as the CLI's own ``--kanbun``
    flag simply being absent when a professor doesn't need it.

    Args:
        sandbox: The already-constructed ``SandboxProcessor`` for this job
                 (see ``ExtensionUiHooks.apply``'s docstring).
        fields: The full submitted composer fields dict; only this hook's
                own ``"kanbun"`` key is read.
    """
    checked = str(fields.get("kanbun", "")).strip().lower() in ("true", "1", "on", "yes")
    if checked and _frags is not None:
        sandbox.translation_service.variant_notes.append(_frags.KANBUN_NOTE)


if _frags is not None:
    register_extension_ui_hooks(
        action_id="translate",
        token="jp",
        fields=[
            UiField(
                name="kanbun",
                label="Use Kanbun reading conventions",
                kind="checkbox",
                required=False,
                group="Japanese (kanbun)",
            ),
        ],
        apply=_apply_kanbun_ui_hook,
    )


# ── Plugin class ───────────────────────────────────────────────────────────────

class EastAsiaTranslationPlugin:
    """Adds Japanese, Chinese, and Korean support to the ``translate`` command.

    Owns Japanese, Chinese, and Korean as *source* languages (so
    ``translate jp-en`` and similar routes here) and contributes East Asia
    destination-side guidance when one of these languages is instead the
    *target* of a translation driven by another plugin. See the module
    docstring above for how this combines with the base translation plugin
    at startup.
    """

    commands: list[str] = ["translate"]

    # Languages this plugin owns as source languages.
    # ``handles`` stores the shortcodes that users type on the command line
    # (e.g. ``jp`` for Japanese), matching the keys in ``LANGUAGE_MAP``.
    # Simplified/Traditional Chinese are handled as flags on ``zh``, not as
    # separate codes.
    handles: list[str] = [
        "jp",
        "zh",
        "kr",
    ]

    # ── Argument registration ──────────────────────────────────────────────────

    def register_command_flags(self, parser: argparse.ArgumentParser) -> None:
        """Add the East-Asia-only command-line flags (``--kanbun``, ``--simplified``, ``--traditional``) to the shared ``translate`` parser.

        Called by ``DispatchPlugin`` once the base plugin has already built
        the ``translate`` subcommand and its universal flags (like
        ``-i``/``--input``). This method only adds the flags specific to
        this plugin's languages.

        Args:
            parser: The argparse subcommand parser the base plugin already
                    created for ``translate``, which this method adds more
                    flags onto in place.
        """
        ea_group = parser.add_argument_group("East Asia options")
        ea_group.add_argument(
            "--kanbun", dest="kanbun", action="store_true",
            help=(
                "Source text is kanbun (漢文): apply kundoku word-order "
                "reconstruction and Classical Chinese reading conventions"
            ),
        )
        script_group = ea_group.add_mutually_exclusive_group()
        script_group.add_argument(
            "--simplified", dest="simplified", action="store_true",
            help=(
                "Source Chinese text uses Simplified characters (简体字); "
                "only valid when source language is zh"
            ),
        )
        script_group.add_argument(
            "--traditional", dest="traditional", action="store_true",
            help=(
                "Source Chinese text uses Traditional characters (繁體字); "
                "only valid when source language is zh"
            ),
        )

    def register_subparsers(
        self,
        subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
    ) -> None:
        """Build a full standalone ``translate`` command, for use without the base plugin installed.

        This is a fallback path, only used when this plugin is running
        without the base translation plugin installed alongside it — an
        unsupported but gracefully handled situation (see the module
        docstring above). In the normal setup, the base plugin builds the
        ``translate`` command via its own ``register_subparsers()``, and
        this plugin only adds its extra flags on top via
        ``register_command_flags()`` above; this method never runs in that
        case.

        Args:
            subparsers: The shared subcommand registry passed in by the CLI
                        startup code, the same object every plugin's
                        commands get added to.
        """
        from plugins.translation.utils import validate_page_nums
        from src.services.constants import DEFAULT_PARALLEL_WORKERS

        p = subparsers.add_parser("translate", help="Translate documents or text (East Asia)")
        p.add_argument(
            "language_code",
            type=parse_language_code,
            help="Translation direction as a source-target pair (e.g. jp-en, zh-en, kr-en)",
        )

        input_group = p.add_mutually_exclusive_group(required=False)
        input_group.add_argument("-i", "--input", dest="input_file", type=str,
                                 help="Input file path (PDF, DOCX, TXT)")
        input_group.add_argument("-c", "--custom", dest="custom_text",
                                 action="store_true", help="Input custom text")

        p.add_argument("-p", "--page_nums", dest="page_nums", type=validate_page_nums,
                       help='Page numbers to process (e.g., "1" or "1-5")')
        p.add_argument("-a", "--abstract", dest="abstract", action="store_true",
                       help="Text has an abstract")
        p.add_argument("--auto-save", dest="auto_save", action="store_true",
                       help="Auto-save with timestamp")
        p.add_argument("--progressive-save", dest="progressive_save", action="store_true",
                       help="Save each page immediately (text output only)")
        p.add_argument("-f", "--font", dest="custom_font", type=str,
                       help="Custom font name (must be in fonts/)")
        p.add_argument("--font-size", dest="font_size", type=int, default=None,
                       metavar="PT", help="Body font size in points (default: 9)")
        p.add_argument("-w", "--workers", dest="workers", type=int,
                       default=DEFAULT_PARALLEL_WORKERS, metavar="N",
                       help="Number of parallel translation workers (default: %(default)s)")
        p.add_argument("--spread", dest="spread", action="store_true",
                       help="Image is a two-page spread")
        p.add_argument("--scanned", dest="scanned", action="store_true",
                       help="Treat PDF as scanned (OCR+translate via vision model)")
        p.add_argument("--preserve-tables", dest="preserve_tables", action="store_true",
                       help="Return tables as Markdown")
        p.add_argument("--preserve-media", dest="preserve_media", action="store_true",
                       help="Carry embedded images from .docx source to .docx output")
        p.add_argument("--toc", dest="toc", action="store_true",
                       help="Normalize table of contents dot leaders")
        add_common_flags(p)
        add_notes_flags(p)
        # EA-specific flags
        self.register_command_flags(p)

    # ── Peer guidance ──────────────────────────────────────────────────────────

    def get_peer_guidance(self, token: str) -> Optional[str]:
        """Provide extra instructions for the AI model when one of this plugin's languages is the translation *target*, not the source.

        Called by ``DispatchPlugin`` when a different plugin is driving a
        translation (because it owns the *source* language) but the
        *destination* language is one this plugin owns — for example,
        translating ``en-jp`` is driven by the base (English) plugin, but
        Japanese is this plugin's language, so this method gets a chance to
        add Japanese-specific guidance to the base plugin's prompt.

        Args:
            token: The short destination-language code being translated
                   into (e.g. ``'jp'``).

        Returns:
            A string of extra instructions to add to the AI model's prompt,
            or ``None`` if this plugin has no special guidance registered
            for that destination language.
        """
        if _frags and hasattr(_frags, 'PEER_GUIDANCE'):
            return _frags.PEER_GUIDANCE.get(token)
        return None

    # ── Command execution ──────────────────────────────────────────────────────

    def run(
        self,
        args: argparse.Namespace,
        professor: str,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
        max_tokens: Optional[int],
    ) -> None:
        """Run the ``translate`` command when Japanese, Chinese, or Korean is the source language.

        Builds a ``SandboxProcessor`` (which resolves the professor's API
        key and sets up token/cost tracking), resolves the source and
        target languages from the requested language-pair code, applies any
        Chinese script-variant flags and kanbun guidance to the translation
        service's notes, then delegates all universal validation and
        execution to the base translation plugin's shared
        ``_execute_translate()`` function.

        Args:
            args: The object holding all the parsed command-line flags for
                  this run (the language pair, input file path, whether
                  ``--kanbun`` was passed, etc.).
            professor: The Princeton NetID whose configuration and API key
                       should be used for this run (e.g. ``'heller'``).
            model: The AI model explicitly requested on the command line, or
                   ``None`` to use the configured default.
            temperature: The requested sampling temperature (controls how
                         predictable vs. varied the model's wording is), or
                         ``None`` to use the default.
            top_p: The requested nucleus-sampling value (an alternative way
                   of controlling response variety), or ``None`` to use the
                   default.
            max_tokens: The requested maximum response length, in tokens
                        (the small chunks of text models process and bill
                        by), or ``None`` to use the default.

        Raises:
            CLIError: If the base translation plugin isn't installed, the
                      language-pair argument is malformed, or
                      ``--simplified``/``--traditional`` is used with a
                      non-Chinese source language.
        """
        from src.runtime.sandbox_processor import SandboxProcessor

        # Base plugin is required for the service layer.
        _base_module = sys.modules.get('pu_plugin.translation.plugin')
        if _base_module is None:
            raise CLIError(
                "The East Asia translation plugin requires the base translation "
                "plugin (plugins/translation/) to be installed and loaded."
            )

        sandbox = SandboxProcessor(
            professor,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )

        language_code = args.language_code
        if not isinstance(language_code, tuple) or len(language_code) != 2:
            raise CLIError("Translation requires a language pair (e.g. jp-en).")
        source_code, target_code = language_code
        source_language = LANGUAGE_MAP.get(source_code, source_code)
        target_language = LANGUAGE_MAP.get(target_code, target_code)

        # Resolve Chinese script variant from flags.
        if source_code == 'zh':
            if getattr(args, 'simplified', False):
                source_language = 'Simplified Chinese'
            elif getattr(args, 'traditional', False):
                source_language = 'Traditional Chinese'
        elif getattr(args, 'simplified', False) or getattr(args, 'traditional', False):
            raise CLIError(
                "--simplified and --traditional are only valid when the source language is zh (Chinese)."
            )

        # EA-specific variant notes — append one per active convention flag.
        # Multiple notes accumulate; each renders as a separate additional-
        # instructions block in the system prompt, in order of appending.
        if _frags and getattr(args, 'kanbun', False):
            sandbox.translation_service.variant_notes.append(_frags.KANBUN_NOTE)

        # Apply any destination-side peer guidance injected by DispatchPlugin.
        for note in getattr(args, '_peer_guidance', []):
            sandbox.translation_service.variant_notes.append(note)

        # Delegate all universal validation and dispatch to the base plugin.
        _base_module._execute_translate(sandbox, args, source_language, target_language)


plugin = EastAsiaTranslationPlugin()
