# East Asia Translation Plugin

Extends the [PU AI Sandbox](https://github.com/princeton-oit/PU_AISandbox) `translate` command with East Asian source-language support: Japanese, Chinese (Simplified and Traditional), and Korean.

**Requires the base translation plugin** (`plugins/translation/`, which ships with the main repo) to be present. The base plugin owns the service layer; this plugin adds EA language routing, East Asian script guidance, and EA-specific CLI flags.

---

## Installation

Clone this repo into the `plugins/translation-ea/` directory inside the main PU_AISandbox repo:

```bash
# From the PU_AISandbox root:
git clone https://github.com/JHGFD82/PU_AISandbox_Translation_EA plugins/translation-ea
```

The plugin is discovered automatically at startup. No changes to the main repo are needed. Because plugin directories are loaded in alphabetical order, the base plugin (`translation/`) always loads first and injects the service layer into `sys.modules` before this plugin runs.

---

## Dispatch Model

When both plugins are installed, the plugin loader merges them into a `DispatchPlugin` that routes each `translate` invocation to whichever plugin owns the source language:

| Source language | Handling plugin |
|---|---|
| English | Base plugin (`plugins/translation/`) |
| Japanese, Chinese, Simplified Chinese, Traditional Chinese, Korean | This plugin |

When translating *into* an East Asian language (e.g. `en-jp`), the base plugin drives the translation and this plugin contributes destination-side conventions via `get_peer_guidance()`. This requires no action from the user.

---

## Configuration

### `settings.toml`

Controls default model parameters. The plugin searches upward from its own directory for a `settings.toml` containing `[translation]` or `[image_translation]`; the main repo's root-level `settings.toml` is found automatically. To override for this plugin only, edit `plugins/translation-ea/settings.toml`:

```toml
[translation]
temperature = 0.5
top_p = 0.5
max_tokens = 4000
context_percentage = 0.65

[image_translation]
temperature = 0.3
max_tokens = 8000
```

---

## Running Tests

```bash
# Activate the main repo's venv first (if not already active):
source ../../.venv/bin/activate        # macOS/Linux

# Run all plugin tests:
cd plugins/translation-ea
pytest

# Run with verbose output, or a specific file:
pytest -v
pytest tests/test_plugin_run.py
```

`pytest.ini` adds the main repo root to `sys.path` automatically via `conftest.py`, so `src.*` imports resolve without extra setup.

Test files:
- `test_preserve_media_cli.py` — covers `--preserve-media`, a base-plugin flag (carried over from the shared plugin template).
- `test_translate_cli.py` — CLI flag parsing for `--kanbun`, `--simplified`, `--traditional`.
- `test_plugin_run.py` — `run()` behavior: Chinese script-variant resolution, kanbun/peer-guidance variant notes, and the requires-base-plugin guard.

---

## Language Codes

| Code | Language |
|------|----------|
| `zh` | Chinese (generic by default; use `--simplified` or `--traditional` to tell the model which script variety the source uses) |
| `jp` | Japanese |
| `kr` | Korean |

Combined with the base-plugin English code `en`: `jp-en` (Japanese → English), `en-jp` (English → Japanese), `zh-en`, `kr-en`, `en-zh`, etc.

---

## Usage

```bash
python main.py <professor> translate <language-code> [options]
```

### Examples

```bash
# Translate a PDF from Japanese to English:
python main.py heller translate jp-en -i article.pdf -o article_en.pdf

# Translate a Word document from Chinese (Traditional), preserving embedded images:
python main.py heller translate zh-en -i paper.docx -o paper_en.docx --preserve-media

# Translate a Word document from Simplified Chinese:
python main.py heller translate zh-en --simplified -i paper.docx -o paper_en.docx

# Translate a kanbun text with kundoku reconstruction:
python main.py heller translate jp-en -i kanbun.txt --kanbun -o output.txt

# Translate specific pages only:
python main.py heller translate zh-en -i book.pdf -p 5-10 -o ch5-10_en.txt

# Translate a scanned PDF (OCR + translation via vision model):
python main.py heller translate jp-en -i scan.pdf --scanned -o scan_en.docx

# Translate a single image:
python main.py heller translate zh-en -i diagram.png -o diagram_en.txt

# Enter custom text interactively:
python main.py heller translate kr-en -c

# Translate in parallel (4 workers):
python main.py heller translate jp-en -i long.pdf -o long_en.pdf -w 4

# Dry run — print prompts without calling the API:
python main.py heller translate zh-en -i article.pdf --dry-run
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

### Output Format

| Flag | Description |
|------|-------------|
| `--auto-save` | Auto-save output with a timestamp suffix. |
| `--progressive-save` | Write each translated page immediately (text output only; disabled with `--workers > 1`). |
| `-f FONT`, `--font FONT` | Custom font name for PDF/DOCX output (must exist in `fonts/`). |
| `--font-size PT` | Body font size in points for PDF/DOCX output (default: 9). |

### Translation Behavior

| Flag | Description |
|------|-------------|
| `-a`, `--abstract` | Document has an abstract; used as context for the model. |
| `--toc` | Document has a table of contents: normalize dot leaders. |
| `--preserve-tables` | Return tabular data as Markdown tables. |
| **`--kanbun`** | **EA only.** Source text is kanbun (漢文): apply kundoku word-order reconstruction and Classical Chinese reading conventions. |
| **`--simplified`** | **EA only (`zh` source).** Treat source as Simplified Chinese. Mutually exclusive with `--traditional`. |
| **`--traditional`** | **EA only (`zh` source).** Treat source as Traditional Chinese. Mutually exclusive with `--simplified`. |

### Media and Document Structure

| Flag | Description |
|------|-------------|
| `--preserve-media` | Copy embedded images from `.docx`/`.pdf` source into the translated `.docx` output. |
| `--scanned` | Treat PDF as a scanned image: render each page and OCR+translate. Cannot combine with `--preserve-media`. |
| `--spread` | Input image is a two-page spread. Applies to image inputs and `--scanned` PDFs. |

### Parallelism

| Flag | Default | Description |
|------|---------|-------------|
| `-w N`, `--workers N` | 1 | Parallel translation workers. Workers > 1 uses untranslated source text as context and disables `--progressive-save`. |

### Model Overrides

| Flag | Description |
|------|-------------|
| `-m MODEL`, `--model MODEL` | Model to use (e.g. `gpt-4o`). |
| `-t FLOAT`, `--temperature FLOAT` | Sampling temperature (0.0–2.0). |
| `-T FLOAT`, `--top-p FLOAT` | Nucleus sampling top-p (0.0–1.0). |
| `-M INT`, `--max-tokens INT` | Maximum response tokens (overrides `settings.toml`). |

### Prompt Notes

| Flag | Description |
|------|-------------|
| `-n`, `--notes` | Interactively append ad-hoc notes to the system prompt, user prompt, or both. |
| `-ns TEXT`, `--note-system TEXT` | Inline note appended to the system prompt. |
| `-nu TEXT`, `--note-user TEXT` | Inline note appended to the user prompt. |
| `-nb TEXT`, `--note-both TEXT` | Inline note appended to both the system and user prompts. |

### Diagnostics

| Flag | Description |
|------|-------------|
| `--dry-run` | Print the prompt(s) without making any API calls. |
