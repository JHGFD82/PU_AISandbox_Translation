# Translation Plugin

Provides the `translate` command for the [PU AI Sandbox](https://github.com/princeton-oit/PU_AISandbox) platform. Supports document translation (PDF, DOCX, TXT), custom text input, and image/scanned-document OCR+translation.

---

## Installation

This plugin must be cloned inside the main PU_AISandbox repository:

```bash
# From the PU_AISandbox root:
git clone <this-repo-url> plugins/translation
```

The plugin is discovered automatically at startup by `src/runtime/plugin_loader.py`. No changes to the main repo are needed.

All dependencies are shared with the main repo's virtual environment — no separate install step is required.

---

## Configuration

### `settings.toml`

Controls default model parameters. Copy and edit to override:

```toml
[translation]
temperature = 0.5          # 0.0 = deterministic, 2.0 = maximum creativity
top_p = 0.5                # Nucleus sampling threshold
max_tokens = 4000          # Maximum response tokens per page
context_percentage = 0.65  # Fraction of the previous page passed as context

[image_translation]
temperature = 0.3
max_tokens = 8000
```

The plugin searches upward from its own directory for the nearest `settings.toml` that contains `[translation]` or `[image_translation]`, so you can also edit the root-level `settings.toml` in the main repo.

### `prompts.toml` (optional)

Override the built-in prompt fragments without editing source code:

```bash
cp plugins/translation/prompts.template.toml prompts.toml
```

Uncomment only the keys you want to change. `prompts.toml` is git-ignored in the main repo. See `prompts.template.toml` for all available keys and placeholders.

---

## Running Tests

Tests live in `tests/` and use the main repo's virtual environment. Run from this plugin's directory:

```bash
# Activate the main repo's venv first (if not already active):
source ../../.venv/bin/activate        # macOS/Linux
# ..\..\.venv\Scripts\activate         # Windows

# Run all plugin tests:
cd plugins/translation
pytest

# Run a specific test file:
pytest tests/test_preserve_media_cli.py

# Run with verbose output:
pytest -v

# Run tests matching a keyword:
pytest -k "preserve_media"
```

`pytest.ini` sets `testpaths = tests` and adds the main repo root to `sys.path` automatically via `pythonpath = ../..`, so `src.*` imports resolve without any extra setup.

---

## Language Codes

Pass a two-character source-target pair as the first positional argument:

| Code | Language |
|------|----------|
| `C`  | Chinese (Classical / Traditional) |
| `S`  | Simplified Chinese |
| `J`  | Japanese |
| `K`  | Korean |
| `E`  | English |

Examples: `C-E` (Chinese → English), `J-E` (Japanese → English), `E-J` (English → Japanese).

Custom codes can be added via a `languages.toml` file in the main repo root (see `languages.template.toml`).

---

## Usage

```bash
python main.py <professor> translate <language-code> [options]
```

### Basic examples

```bash
# Translate a PDF from Chinese to English, save to file:
python main.py heller translate C-E -i article.pdf -o article_en.pdf

# Translate a Word document, preserving embedded images:
python main.py heller translate J-E -i paper.docx -o paper_en.docx --preserve-media

# Translate specific pages only:
python main.py heller translate C-E -i book.pdf -p 5-10 -o ch5-10_en.txt

# Translate a scanned PDF (OCR + translation via vision model):
python main.py heller translate J-E -i scan.pdf --scanned -o scan_en.docx

# Translate a single image (OCR + translation):
python main.py heller translate C-E -i diagram.png -o diagram_en.txt

# Enter custom text interactively:
python main.py heller translate C-E -c

# Translate in parallel (4 workers):
python main.py heller translate J-E -i long.pdf -o long_en.pdf -w 4

# Dry run — print prompts without calling the API:
python main.py heller translate C-E -i article.pdf --dry-run
```

---

## Flag Reference

### Input / Output

| Flag | Description |
|------|-------------|
| `-i FILE`, `--input FILE` | Input file (PDF, DOCX, TXT, or image). Mutually exclusive with `-c`. |
| `-c`, `--custom` | Enter custom text interactively. Mutually exclusive with `-i`. |
| `-o FILE`, `--output FILE` | Output file path. Extension determines format: `.txt`, `.pdf`, `.docx`. |
| `-p RANGE`, `--page_nums RANGE` | Pages to process, e.g. `1` or `3-7` (PDF/DOCX only). |

### Output format

| Flag | Description |
|------|-------------|
| `--auto-save` | Auto-save output with a timestamp suffix. |
| `--progressive-save` | Write each translated page to the output file immediately (text output only; disabled with `--workers > 1`). |
| `-f FONT`, `--font FONT` | Custom font name for PDF/DOCX output (font file must exist in `fonts/`). |
| `--font-size PT` | Body font size in points for PDF/DOCX output (default: 9). |

### Translation behavior

| Flag | Description |
|------|-------------|
| `-a`, `--abstract` | Treat the document as having an abstract; passed as context to the model. |
| `--kanbun` | Source text is kanbun (漢文): apply kundoku word-order reconstruction and Classical Chinese reading conventions. |
| `--toc` | Document contains a table of contents: normalize dot leaders to five dots between titles and page numbers. |
| `--preserve-tables` | Hint the model to return tabular data as Markdown tables; rendered as proper tables in PDF/DOCX output. |

### Media and document structure

| Flag | Description |
|------|-------------|
| `--preserve-media` | Copy embedded images from the source `.docx` or `.pdf` into the translated `.docx` output. Requires `-i` and `-o` with `.docx` extension. |
| `--scanned` | Treat the PDF as a scanned image document: render each page as an image and use OCR+translation. PDF only; cannot be combined with `--preserve-media`. |
| `--spread` | Input image is a two-page spread (two facing pages scanned together). Applies to image inputs and `--scanned` PDFs. |

### Parallelism

| Flag | Default | Description |
|------|---------|-------------|
| `-w N`, `--workers N` | 1 | Number of parallel translation workers. Each page is sent as an independent API call. Workers > 1 uses untranslated source text as context and disables `--progressive-save`. |

### Model overrides

| Flag | Description |
|------|-------------|
| `-m MODEL`, `--model MODEL` | Model to use (e.g. `gpt-4o`, `openai/gpt-4o-mini`). |
| `-t FLOAT`, `--temperature FLOAT` | Sampling temperature override (0.0–2.0). |
| `-T FLOAT`, `--top-p FLOAT` | Nucleus sampling top-p override (0.0–1.0). |
| `-M INT`, `--max-tokens INT` | Maximum response tokens (overrides `settings.toml` default). |

### Prompt notes

| Flag | Description |
|------|-------------|
| `-n`, `--notes` | Interactively append ad-hoc notes to the system prompt, user prompt, or both before sending. |
| `-ns TEXT`, `--note-system TEXT` | Inline note appended to the system prompt. |
| `-nu TEXT`, `--note-user TEXT` | Inline note appended to the user prompt. |
| `-nb TEXT`, `--note-both TEXT` | Inline note appended to both the system and user prompts. |

### Diagnostics

| Flag | Description |
|------|-------------|
| `--dry-run` | Print the prompt(s) that would be sent without making any API calls. |
