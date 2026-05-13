"""PU_AISandbox East Asia Translation plugin.

Provides ``translate`` support for East Asian source languages (Japanese,
Chinese, Korean).  Requires the base translation plugin (plugins/translation/)
to be present in the same PU_AISandbox installation — the base plugin owns
the shared service layer (TranslationService, ImageTranslationService, and
all prompt specs) and must load first.

Clone this repo into ``plugins/translation-ea/`` inside the PU_AISandbox repo.

DISPATCH MODEL
--------------
When both this plugin and the base translation plugin are loaded, the plugin
loader detects that both register ``translate`` and both declare ``handles``.
Rather than treating this as a conflict, it merges them into a DispatchPlugin
that routes each invocation to the plugin owning the source language:

  translate jp-en  → this plugin owns Japanese, drives translation
  translate en-jp  → base plugin owns English, drives translation;
                   this plugin contributes Japanese destination guidance
  translate jp-fr  → this plugin drives; French plugin (if loaded) contributes
                   destination guidance; no French plugin → proceeds without it

EA-SPECIFIC FEATURES
--------------------
  --kanbun     Source text is kanbun (漢文): apply kundoku word-order
             reconstruction and classical Chinese reading conventions.
             Appends KANBUN_NOTE (from fragments.py) to variant_notes on the
             translation service before delegating to the shared executor.

  --simplified / --traditional
             Source Chinese text uses a specific script variety.
             Changes the resolved source language from "Chinese" to
             "Simplified Chinese" or "Traditional Chinese" in the prompt.
             Mutually exclusive; only valid when the source language is ``zh``.

FRAGMENT REGISTRATION
---------------------
At import time this plugin loads fragments.py and registers East Asia script
guidance and language-pair notes into the base plugin's translation_fragments
module via setdefault(), so the first-loaded plugin's entry always wins if
two language plugins ever register the same token.
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
    """Load a module local to this plugin and register it in sys.modules.

    Returns the loaded module, or None if the file does not exist.
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


# ── Plugin class ───────────────────────────────────────────────────────────────

class EastAsiaTranslationPlugin:
    """East Asia translation plugin.  Owns Japanese, Chinese, and Korean as
    source languages and contributes East Asia destination guidance.
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
        """Add East Asia-specific flags to an existing 'translate' subparser.

        Called by DispatchPlugin when building the merged parser.  Only EA-
        owned flags belong here — universal flags are registered by the base
        plugin via its own register_command_flags() call.
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
        """Register a standalone 'translate' subcommand.

        Used only when this plugin loads without a DispatchPlugin (i.e. the
        base translation plugin is absent — an unsupported but gracefully
        handled configuration).  In the normal two-plugin setup, DispatchPlugin
        calls register_command_flags() on this plugin instead.
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
        """Return destination-side guidance when an EA language is the target.

        Called by DispatchPlugin when this plugin owns the destination language
        and a different plugin is driving the translation.  Returns a string to
        inject EA destination conventions into the source plugin's prompt, or
        None if no special guidance is needed for this target.
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
        """Execute the translate command for an East Asian source language."""
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
