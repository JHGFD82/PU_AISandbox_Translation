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
from src.errors import CLIError                                    # noqa: E402
from src.models import OutputOptions                               # noqa: E402
from src.processors.constants import IMAGE_EXTENSIONS             # noqa: E402
from src.processors.docx_processor import DocxProcessor           # noqa: E402
from src.processors.pdf_processor import generate_process_text    # noqa: E402
from src.processors.txt_processor import TxtProcessor             # noqa: E402
from src.services.constants import DEFAULT_PARALLEL_WORKERS       # noqa: E402
from src.settings import DEFAULT_PAGE_SIZE                        # noqa: E402


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
        """Execute the translate command."""
        import os
        from src.runtime.sandbox_processor import SandboxProcessor

        sandbox = SandboxProcessor(
            professor,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )

        language_code = args.language_code

        if not isinstance(language_code, tuple) or len(language_code) != 2:
            raise CLIError("Translation requires a 2-character language code (e.g., CE, JE, KE)")

        source_language: str = language_code[0]
        target_language: str = language_code[1]

        # --scanned compatibility checks
        if getattr(args, 'scanned', False):
            _scanned_input: Optional[str] = getattr(args, 'input_file', None)
            if not _scanned_input:
                raise CLIError("--scanned requires a file input (-i).")
            if getattr(args, 'custom_text', False):
                raise CLIError("Cannot use --scanned with custom text input (-c).")
            _scanned_ext = os.path.splitext(_scanned_input)[1].lower()
            if _scanned_ext != '.pdf':
                raise CLIError(
                    f"--scanned is only valid for PDF files (got '{_scanned_ext}'). "
                    "For image files, the translate command routes through OCR automatically."
                )
            if getattr(args, 'preserve_media', False):
                raise CLIError("Cannot combine --scanned with --preserve-media.")

        # --preserve-media compatibility checks
        if getattr(args, 'preserve_media', False):
            if getattr(args, 'progressive_save', False):
                raise CLIError("Cannot combine --preserve-media with --progressive-save.")
            if getattr(args, 'custom_text', False):
                raise CLIError(
                    "Cannot use --preserve-media with custom text input (-c): "
                    "pasted text contains no embedded media."
                )
            input_file_arg: Optional[str] = getattr(args, 'input_file', None)
            if not input_file_arg:
                raise CLIError(
                    "Cannot use --preserve-media without a file input (-i)."
                )
            input_ext = os.path.splitext(input_file_arg)[1].lower()
            if input_ext in IMAGE_EXTENSIONS:
                raise CLIError(
                    "Cannot use --preserve-media with an image file input: "
                    "images have no embedded media to carry over."
                )
            if input_ext not in ('.docx', '.pdf'):
                raise CLIError(
                    f"Cannot use --preserve-media with '{input_ext}' files: "
                    "media preservation supports Word documents (.docx) and PDF files (.pdf)."
                )
            output_file_arg: Optional[str] = getattr(args, 'output_file', None)
            if getattr(args, 'auto_save', False) and not output_file_arg:
                raise CLIError(
                    "Cannot use --preserve-media with --auto-save: auto-save produces a .txt file. "
                    "Specify a .docx output with -o."
                )
            if not output_file_arg:
                raise CLIError(
                    "Cannot use --preserve-media without a .docx output file. "
                    "Specify an output with -o, e.g. -o translated.docx."
                )
            out_ext = os.path.splitext(output_file_arg)[1].lower()
            if out_ext == '.txt':
                raise CLIError(
                    "--preserve-media requires a .docx output file; "
                    ".txt files cannot embed images."
                )
            if out_ext == '.pdf':
                raise CLIError(
                    "--preserve-media does not yet support PDF output. "
                    "Specify a .docx output file with -o."
                )
            if out_ext != '.docx':
                raise CLIError(
                    "--preserve-media requires a .docx output file "
                    f"(got '{out_ext}')."
                )

        if getattr(args, 'notes', False):
            _preview_sys: Optional[str] = None
            _preview_usr: Optional[str] = None
            if args.input_file:
                _fp = os.path.abspath(args.input_file)
                if os.path.exists(_fp) and sandbox.image_processor.is_image_file(_fp):
                    _preview_sys, _preview_usr = sandbox.image_translation_service.build_prompts(
                        source_language, target_language
                    )
                else:
                    _placeholder = generate_process_text("", f"[{source_language} document text]", "")
                    _preview_sys, _preview_usr = sandbox.translation_service.build_prompts(
                        _placeholder, source_language, target_language
                    )
            else:
                _placeholder = generate_process_text("", f"[{source_language} custom text]", "")
                _preview_sys, _preview_usr = sandbox.translation_service.build_prompts(
                    _placeholder, source_language, target_language
                )
            sys_note, usr_note = sandbox._collect_notes(_preview_sys, _preview_usr)
            sandbox.translation_service.system_note = sys_note
            sandbox.translation_service.user_note = usr_note
            sandbox.image_translation_service.system_note = sys_note
            sandbox.image_translation_service.user_note = usr_note

        sandbox._apply_inline_notes(sandbox.translation_service, args)
        sandbox._apply_inline_notes(sandbox.image_translation_service, args)

        if getattr(args, 'kanbun', False):
            sandbox.translation_service.kanbun = True

        if getattr(args, 'preserve_tables', False):
            sandbox.translation_service.tables = True
            sandbox.image_translation_service.tables = True

        if getattr(args, 'toc', False):
            sandbox.translation_service.toc = True

        if getattr(args, 'dry_run', False):
            model_dr = sandbox.translation_service._get_model()
            abstract_text_dr: Optional[str] = None
            if getattr(args, 'abstract', False):
                abstract_text_dr = sandbox._collect_multiline("Abstract text") or None

            if args.input_file:
                file_path_dr = os.path.abspath(args.input_file)
                file_type_dr = sandbox._detect_and_validate_file(file_path_dr)
                if file_type_dr == 'image':
                    spread_dr = getattr(args, 'spread', False)
                    sys_p, usr_p = sandbox.image_translation_service.build_prompts(source_language, target_language, spread=spread_dr)
                    sandbox._dry_run_display(
                        sandbox.image_translation_service._get_model(), sys_p, usr_p,
                        note="Image content would be base64-encoded and attached to the user message",
                        **sandbox._sampling_kwargs(args),
                    )
                    return
                elif file_type_dr == 'pdf':
                    if getattr(args, 'scanned', False):
                        spread_dr = getattr(args, 'spread', False)
                        sys_p, usr_p = sandbox.image_translation_service.build_prompts(
                            source_language, target_language, spread=spread_dr
                        )
                        sandbox._dry_run_display(
                            sandbox.image_translation_service._get_model(), sys_p, usr_p,
                            note="Scanned PDF: each page will be rendered as an image and attached to the user message",
                            **sandbox._sampling_kwargs(args),
                        )
                        return
                    with open(file_path_dr, 'rb') as f:
                        first_page = next(iter(sandbox.pdf_processor.process_pdf(f)), None)
                        page_text_dr = sandbox.pdf_processor.process_page(first_page) if first_page else "[no text found in PDF]"
                elif file_type_dr == 'docx':
                    with open(file_path_dr, 'rb') as f:
                        pages_dr = DocxProcessor.process_docx_with_pages(f, target_page_size=DEFAULT_PAGE_SIZE)
                        page_text_dr = pages_dr[0] if pages_dr else "[no text found in document]"
                elif file_type_dr == 'txt':
                    with open(file_path_dr, 'r', encoding='utf-8') as f:
                        pages_dr = TxtProcessor.process_txt_with_pages(f, target_page_size=DEFAULT_PAGE_SIZE)
                        page_text_dr = pages_dr[0] if pages_dr else "[no text found in file]"
                else:
                    page_text_dr = f"[{source_language} text to translate]"
            elif args.custom_text:
                page_text_dr = sandbox._collect_multiline(
                    f"Enter the {source_language} text you want to translate to {target_language}"
                )
                if not page_text_dr.strip():
                    page_text_dr = f"[{source_language} text to translate]"
            else:
                page_text_dr = f"[{source_language} text to translate]"

            combined = generate_process_text(abstract_text_dr or "", page_text_dr, "")
            context_type_dr = "abstract" if abstract_text_dr else "none"
            output_file_dr = getattr(args, 'output_file', None)
            auto_save_dr = getattr(args, 'auto_save', False)
            if output_file_dr:
                ext = output_file_dr.lower().rsplit('.', 1)[-1] if '.' in output_file_dr else ''
                output_format_dr = {'pdf': 'pdf', 'docx': 'docx', 'txt': 'txt'}.get(ext, 'file')
            elif auto_save_dr:
                output_format_dr = 'txt'
            else:
                output_format_dr = 'console'
            sys_p, usr_p = sandbox.translation_service.build_prompts(combined, source_language, target_language, output_format=output_format_dr, context_type=context_type_dr)
            sandbox._dry_run_display(model_dr, sys_p, usr_p, **sandbox._sampling_kwargs(args))
            return

        opts = OutputOptions(
            output_file=sandbox._resolve_output_path(args),
            auto_save=getattr(args, 'auto_save', False),
            progressive_save=getattr(args, 'progressive_save', False),
            custom_font=getattr(args, 'custom_font', None),
            preserve_media=getattr(args, 'preserve_media', False),
            font_size=getattr(args, 'font_size', None),
        )
        workers = getattr(args, 'workers', 1)
        spread = getattr(args, 'spread', False)
        if args.custom_text:
            sandbox.translate_custom_text(
                source_language,
                target_language,
                getattr(args, 'abstract', False),
                opts,
            )
        elif args.input_file:
            input_path = os.path.abspath(args.input_file)
            if os.path.isdir(input_path):
                sandbox.process_image_translation_folder(
                    input_path,
                    source_language,
                    target_language,
                    opts,
                    workers=workers,
                    spread=spread,
                )
            else:
                sandbox.translate_document(
                    args.input_file,
                    source_language,
                    target_language,
                    getattr(args, 'page_nums', None),
                    getattr(args, 'abstract', False),
                    opts,
                    workers=workers,
                    spread=spread,
                    scanned=getattr(args, 'scanned', False),
                )
        else:
            raise CLIError("No input specified. Use -i for file input or -c for custom text.")


plugin = TranslationPlugin()
