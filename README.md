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

When translating *into* an East Asian language (e.g. `E-J`), the base plugin drives the translation and this plugin contributes destination-side conventions via `get_peer_guidance()`. This requires no action from the user.

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

### `prompts.toml` (optional)

Override built-in prompt fragments without editing source code:

```bash
cp plugins/translation-ea/prompts.template.toml prompts.toml
```

Place `prompts.toml` in the PU_AISandbox root. It is git-ignored and will not be committed. Uncomment only the keys you want to change. Fragment defaults are defined in `plugins/translation/src/services/prompts/translation_fragments.py` (base plugin) and `plugins/translation-ea/fragments.py` (EA additions).

---

## Running Tests

```bash
# Activate the main repo's venv first (if not already active):
source ../../.venv/bin/activate        # macOS/Linux

# Run all plugin tests:
cd plugins/translation-ea
pytest

# Run with verbose output or a specific file/keyword:
pytest -v
pytest tests/test_image_translation.py
pytest -k "kanbun"
```

`pytest.ini` adds the main repo root to `sys.path` automatically via `conftest.py`, so `src.*` imports resolve without extra setup.

---

## Language Codes

| Code | Language |
|------|----------|
| `C`  | Chinese (Classical / Traditional) |
| `S`  | Simplified Chinese |
| `J`  | Japanese |
| `K`  | Korean |

Combined with base-plugin codes (e.g. `E` for English): `J-E` (Japanese → English), `E-J` (English → Japanese), `C-E`, `K-E`, `S-E`, etc.

Custom codes can be added via `languages.toml` in the main repo root (see `languages.template.toml`).

---

## Usage

```bash
python main.py <professor> translate <language-code> [options]
```

### Examples

```bash
# Translate a PDF from Japanese to English:
python main.py heller translate J-E -i article.pdf -o article_en.pdf

# Translate a Word document from Chinese, preserving embedded images:
python main.py heller translate C-E -i paper.docx -o paper_en.docx --preserve-media

# Translate a kanbun text with kundoku reconstruction:
python main.py heller translate J-E -i kanbun.txt --kanbun -o output.txt

# Translate specific pages only:
python main.py heller translate C-E -i book.pdf -p 5-10 -o ch5-10_en.txt

# Translate a scanned PDF (OCR + translation via vision model):
python main.py heller translate J-E -i scan.pdf --scanned -o scan_en.docx

# Translate a single image:
python main.py heller translate C-E -i diagram.png -o diagram_en.txt

# Enter custom text interactively:
python main.py heller translate K-E -c

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
