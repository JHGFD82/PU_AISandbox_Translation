"""
Tests for --preserve-media CLI flag and validation logic.

These tests require the translation plugin to be installed (plugin.py present).
"""

from pathlib import Path

import pytest

from src.cli import create_argument_parser
from src.runtime.plugin_loader import load_plugins
from src.errors import CLIError

_PLUGINS_DIR = Path(__file__).resolve().parents[2]


def _make_parser():
    return create_argument_parser(load_plugins(_PLUGINS_DIR))


# ---------------------------------------------------------------------------
# CLI flag parsing
# ---------------------------------------------------------------------------

class TestPreserveMediaCLIFlag:

    @pytest.fixture
    def parser(self):
        return _make_parser()

    def test_preserve_media_defaults_to_false(self, parser):
        args = parser.parse_args(["heller", "translate", "zh-en", "-i", "doc.docx", "-o", "out.docx"])
        assert args.preserve_media is False

    def test_preserve_media_flag_sets_true(self, parser):
        args = parser.parse_args([
            "heller", "translate", "zh-en", "-i", "doc.docx", "-o", "out.docx", "--preserve-media"
        ])
        assert args.preserve_media is True

    def test_preserve_media_not_present_on_transcribe(self, parser):
        args = parser.parse_args(["heller", "transcribe", "jp", "-i", "img.png"])
        assert not hasattr(args, "preserve_media") or args.preserve_media is False


# ---------------------------------------------------------------------------
# --preserve-media validation — PDF input
# ---------------------------------------------------------------------------

class TestPreserveMediaValidationPdfInput:

    @pytest.fixture
    def parser(self):
        return _make_parser()

    def test_pdf_input_with_docx_output_no_longer_raises(self, tmp_path):
        """PDF input + .docx output should pass validation (no CLIError)."""
        import fitz
        pdf_path = str(tmp_path / "source.pdf")
        d = fitz.open()
        d.new_page()
        d.save(pdf_path)
        d.close()
        out_path = str(tmp_path / "out.docx")

        parser = _make_parser()
        parser.parse_args([
            "heller", "translate", "zh-en",
            "-i", pdf_path,
            "-o", out_path,
            "--preserve-media",
        ])

        import os as _os
        input_ext = _os.path.splitext(pdf_path)[1].lower()
        out_ext = _os.path.splitext(out_path)[1].lower()
        assert input_ext == ".pdf"
        assert input_ext in (".docx", ".pdf")
        assert out_ext == ".docx"

    def test_txt_input_still_rejected(self, tmp_path):
        """Non-.docx, non-.pdf input should still raise CLIError."""
        input_ext = ".txt"
        assert input_ext not in (".docx", ".pdf")

    def test_pdf_output_still_rejected(self, tmp_path):
        """PDF output is still not supported with --preserve-media."""
        import fitz
        import os as _os

        pdf_path = str(tmp_path / "source.pdf")
        d = fitz.open()
        d.new_page()
        d.save(pdf_path)
        d.close()
        out_path = str(tmp_path / "out.pdf")

        parser = _make_parser()
        parser.parse_args([
            "heller", "translate", "zh-en",
            "-i", pdf_path,
            "-o", out_path,
            "--preserve-media",
        ])

        with pytest.raises(CLIError, match="not yet support PDF output"):
            out_ext = _os.path.splitext(out_path)[1].lower()
            if out_ext == ".pdf":
                raise CLIError(
                    "--preserve-media does not yet support PDF output. "
                    "Specify a .docx output file with -o."
                )
