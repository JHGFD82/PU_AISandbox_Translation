"""PU_AISandbox Translation plugin.

Provides the ``translate`` command (documents, custom text, and images).
Clone this repo into ``plugins/translation/`` in the main PU_AISandbox repo.

ARCHITECTURE — sys.modules injection
--------------------------------------
``_register()`` (called at import time) injects each extracted service module
into ``sys.modules`` under the same ``src.services.*`` name it had in the main
repo.  This is the mechanism that keeps everything importable after the service
files are removed from the main repo's ``src/`` directory (Phase 4 Step 5).

For the injection to take effect *before* sandbox_processor.py's top-level
imports run, Phase 4 Step 6 must make those imports lazy (deferred to
``__init__`` or wrapped in ``try/except``).

run() — delegation pattern
-----------------------------
``run()`` currently delegates to ``SandboxProcessor._run_translate()``.  This
will be replaced in Phase 4 Step 6 when the translate dispatch logic is moved
from SandboxProcessor into this plugin (so the main repo no longer needs the
translation-specific _run_translate method).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Optional

# ── Module registration (must run at import time) ────────────────────────────

_PLUGIN_DIR = Path(__file__).parent


def _register(module_name: str, rel_path: str) -> None:
    """Inject a plugin module into sys.modules under the src.* namespace.

    If the module is already present (main repo's version loaded first), the
    registration is skipped.  After Phase 4 Step 5 (main repo files deleted)
    and Step 6 (sandbox_processor imports made lazy), this becomes the only
    source for these modules.
    """
    if module_name in sys.modules:
        return
    path = _PLUGIN_DIR / rel_path
    if not path.exists():
        return
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]


# Register in dependency order: fragments → specs → services
_register(
    "src.services.prompts.translation_fragments",
    "src/services/prompts/translation_fragments.py",
)
_register(
    "src.services.prompts.translation",
    "src/services/prompts/translation.py",
)
_register(
    "src.services.prompts.image_translation",
    "src/services/prompts/image_translation.py",
)
_register(
    "src.services.translation_service",
    "src/services/translation_service.py",
)
_register(
    "src.services.image_translation_service",
    "src/services/image_translation_service.py",
)

# ── Main-repo imports ─────────────────────────────────────────────────────────
# These are available because the main PU_AISandbox root is on sys.path
# when running from that repo's root directory.

from src.cli import _add_common_flags, _add_notes_flags           # noqa: E402
from src.config import parse_language_code, validate_page_nums    # noqa: E402
from src.services.constants import DEFAULT_PARALLEL_WORKERS       # noqa: E402


# ── Plugin class ──────────────────────────────────────────────────────────────

class TranslationPlugin:
    """Translation and image-translation mode plugin."""

    commands: list[str] = ["translate"]

    # ── Argument registration ─────────────────────────────────────────────────

    def register_subparsers(
        self,
        subparsers: argparse._SubParsersAction,
    ) -> None:
        p = subparsers.add_parser("translate", help="Translate documents or text")
        p.add_argument(
            "language_code",
            type=parse_language_code,
            help="Translation direction (CE, JE, KE, etc.)",
        )

        input_group = p.add_mutually_exclusive_group(required=False)
        input_group.add_argument(
            "-i", "--input",
            dest="input_file",
            type=str,
            help="Input file path (PDF, DOCX, TXT)",
        )
        input_group.add_argument(
            "-c", "--custom",
            dest="custom_text",
            action="store_true",
            help="Input custom text",
        )

        p.add_argument(
            "-p", "--page_nums",
            dest="page_nums",
            type=validate_page_nums,
            help='Page numbers to process (e.g., "1" or "1-5")',
        )
        p.add_argument("-a", "--abstract", dest="abstract", action="store_true",
                       help="Text has an abstract")
        p.add_argument("--auto-save", dest="auto_save", action="store_true",
                       help="Auto-save with timestamp")
        p.add_argument("--progressive-save", dest="progressive_save",
                       action="store_true",
                       help="Save each page immediately (text output only)")
        p.add_argument("-f", "--font", dest="custom_font", type=str,
                       help="Custom font name (must be in fonts/)")
        p.add_argument("--font-size", dest="font_size", type=int, default=None,
                       metavar="PT",
                       help="Body font size in points for PDF/Word output (default: 9)")
        p.add_argument(
            "--kanbun", dest="kanbun", action="store_true",
            help=(
                "Source text is kanbun (漢文): apply kundoku word-order "
                "reconstruction and Classical Chinese reading conventions"
            ),
        )
        p.add_argument(
            "-w", "--workers",
            dest="workers",
            type=int,
            default=DEFAULT_PARALLEL_WORKERS,
            metavar="N",
            help=(
                "Number of parallel translation workers (default: %(default)s). "
                "Each page is sent as an independent API call. "
                "Workers > 1 uses untranslated source text as context and "
                "disables progressive save."
            ),
        )
        p.add_argument("--spread", dest="spread", action="store_true",
                       help="Image is a two-page spread (two facing pages scanned together); "
                            "applies to image file inputs and --scanned PDFs")
        p.add_argument(
            "--scanned", dest="scanned", action="store_true",
            help="Treat the PDF as a scanned image document: each page is rendered "
                 "as an image and processed via the OCR+translation pipeline "
                 "(vision model). PDF only.",
        )
        p.add_argument(
            "--preserve-tables", dest="preserve_tables", action="store_true",
            help="Hint to the model that tabular data should be returned as Markdown "
                 "tables; the output layer renders them as proper tables in PDF/DOCX "
                 "or ASCII in TXT.",
        )
        p.add_argument(
            "--preserve-media", dest="preserve_media", action="store_true",
            help="Carry embedded images from a .docx source into the translated "
                 ".docx output (requires -i *.docx and -o *.docx)",
        )
        p.add_argument(
            "--toc", dest="toc", action="store_true",
            help="Document contains a table of contents: normalize dot leaders "
                 "(e.g. '............') to exactly five dots (.....) between "
                 "section titles and page numbers",
        )
        _add_common_flags(p)
        _add_notes_flags(p)

    # ── Command execution ─────────────────────────────────────────────────────

    def run(
        self,
        args: argparse.Namespace,
        professor: str,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
        max_tokens: Optional[int],
    ) -> None:
        """Execute the translate command.

        Currently delegates to SandboxProcessor._run_translate().
        TODO (Phase 4 Step 6): move the full translate dispatch logic here
        and remove _run_translate from SandboxProcessor / _CommandMixin.
        """
        from src.runtime.sandbox_processor import SandboxProcessor

        sandbox = SandboxProcessor(
            professor,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        sandbox._run_translate(args)


plugin = TranslationPlugin()
