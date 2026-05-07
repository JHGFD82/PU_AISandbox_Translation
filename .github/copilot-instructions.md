# Translation Plugin — AI Coding Assistant Instructions

## Plugin Overview
This is the `translate` command plugin for [PU AI Sandbox](https://github.com/princeton-oit/PU_AISandbox). It provides document translation (PDF, DOCX, TXT), interactive custom-text translation, and combined OCR + translation for images and scanned PDFs.

This repo lives at `plugins/translation/` inside the main PU_AISandbox repo. All `src.*` imports (e.g. `src.cli`, `src.runtime`, `src.processors`) resolve against the main repo's `src/` — they are *not* in this plugin's directory.

---

## Repository Layout

```text
plugin.py                        ModePlugin entry point; also handles sys.modules injection
settings.toml                    Default model parameters (temperature, top_p, max_tokens, context_percentage)
prompts.template.toml            Template for prompt fragment overrides (copy → prompts.toml at main repo root)
conftest.py                      Inserts main repo root into sys.path for pytest
pytest.ini                       testpaths=tests, pythonpath=../..
src/
  settings.py                    Loads settings.toml; exposes TRANSLATION_*, IMAGE_TRANSLATION_*, CONTEXT_PERCENTAGE
  services/
    translation_service.py       TranslationService — page-by-page translation, parallel workers, context passing
    image_translation_service.py ImageTranslationService — single-pass OCR + translation via vision model
    prompts/
      translation_fragments.py   All raw prompt strings (source of truth); no logic, str.format() placeholders
      translation.py             TranslationPromptSpec dataclass — assembles system + user prompts for text translation
      image_translation.py       ImageTranslationPromptSpec dataclass — assembles prompts for image OCR+translation
tests/
  test_preserve_media_cli.py     CLI flag parsing and --preserve-media validation tests
```

---

## Architecture: sys.modules Injection

`plugin.py` calls `_register()` at import time to inject each `src/services/*` module into `sys.modules` under its canonical `src.services.*` name. This makes the plugin's local copies available to the main repo's runtime without duplicating the import paths.

**Injection order matters** — always register in dependency order:
1. `pu_plugin.translation.settings` (settings.py — registered under a plugin-private name so it doesn't collide with the main repo's `src.settings`)
2. `src.services.prompts.translation_fragments`
3. `src.services.prompts.translation`
4. `src.services.prompts.image_translation`
5. `src.services.translation_service`
6. `src.services.image_translation_service`

If a module is already in `sys.modules` (main repo loaded it first), `_register()` skips it. Never change this skip-if-present guard.

---

## Prompt Architecture

### Fragments (`translation_fragments.py`)
Single source of truth for all prompt text. Contains only constants and dicts — no logic. All variable parts use `str.format()` with named placeholders like `{source}`, `{target}`, `{note}`.

Key constants:
- `TRANSLATION_ROLE` — system role sent on every translation call
- `TRANSLATION_CONTEXT_SPEC_NONE/ABSTRACT/PREVIOUS` — context-handling instruction variants
- `TRANSLATION_FORMATTING` — `{"file": ..., "console": ...}` keyed by output format group
- `LANGUAGE_PAIR_NOTES` — `{(source, target): note}` dict for language-pair-specific rules
- `IMAGE_TRANSLATION_ROLE`, `IMAGE_TRANSLATION_FORMAT_SPEC`, etc. — image pipeline fragments
- `IMAGE_TRANSLATION_SCRIPT_GUIDANCE` — `{language: note}` for script-specific OCR hints

### Prompt Specs (`translation.py`, `image_translation.py`)
`TranslationPromptSpec` and `ImageTranslationPromptSpec` are `@dataclass` classes. They accept flags matching the CLI options and expose `system_prompt()` / `user_prompt()` methods that assemble the final strings from fragments.

**When adding a new flag that affects prompts**: add a field to the relevant spec, add the fragment to `translation_fragments.py`, wire it in the spec's `system_prompt()` / `user_prompt()`, and add the fragment key to `prompts.template.toml`.

### `prompts.toml` overrides
Users can drop a `prompts.toml` in the main repo root to override any fragment without editing source. The override contract (which keys map to which fragments) is defined in `translation_fragments.py` and documented in `prompts.template.toml`. Do not remove or rename fragment constants without updating the template.

---

## Settings

`src/settings.py` walks up from its own path to find the nearest `settings.toml` containing `[translation]` or `[image_translation]`. This means the user can edit either `plugins/translation/settings.toml` or the main repo's root `settings.toml` — whichever is closer wins.

Exposed constants (all have fallback defaults in code):
- `TRANSLATION_TEMPERATURE`, `TRANSLATION_TOP_P`, `TRANSLATION_MAX_TOKENS`, `CONTEXT_PERCENTAGE`
- `IMAGE_TRANSLATION_TEMPERATURE`, `IMAGE_TRANSLATION_MAX_TOKENS`

---

## Services

### `TranslationService`
- Accepts a file path (PDF/DOCX/TXT) or raw text.
- Pages are translated sequentially by default; `workers > 1` enables `ThreadPoolExecutor` parallel mode.
- Passes a context slice (tail of the previous page, sized by `CONTEXT_PERCENTAGE`) to each API call.
- `self.kanbun`, `self.tables`, `self.toc` are set by `plugin.py` before calling the service.
- `_blank_page_count` and `_api_error_count` are thread-safe counters for summary logging.

### `ImageTranslationService`
- Sends one vision API call per image: transcript + translation in a single response.
- `_get_model()` resolves to the catalog's `image_translation` default unless overridden.
- `_get_max_tokens()` checks the per-model catalog override before falling back to `IMAGE_TRANSLATION_MAX_TOKENS`.

---

## `plugin.py` — ModePlugin Contract

`TranslationPlugin` satisfies the main repo's `ModePlugin` protocol:
- `commands = ["translate"]`
- `register_subparsers(subparsers)` — adds the `translate` subparser with all flags
- `run(args, professor, model, temperature, top_p, max_tokens)` — validates flags, wires services, delegates to `SandboxProcessor._run_translate()`

**Flag validation in `run()`** — compatibility checks (in order):
1. `--scanned`: requires `-i`, no `-c`, PDF only, incompatible with `--preserve-media`
2. `--preserve-media`: incompatible with `--progressive-save`, `-c`; requires `-i`; input must be `.docx` or `.pdf`; output must be `.docx`

Always add new flag validation here, not in `register_subparsers`.

---

## Testing

Tests run from this plugin's directory using the main repo's venv:

```bash
cd plugins/translation
pytest                        # all tests
pytest -v                     # verbose
pytest -k "preserve_media"    # filter by keyword
```

`pytest.ini` sets `pythonpath = ../..` (main repo root) and `testpaths = tests`.  
`conftest.py` inserts the main repo root into `sys.path` at collection time for compatibility.

`tests/test_preserve_media_cli.py` uses `create_argument_parser(load_plugins(_PLUGINS_DIR))` where `_PLUGINS_DIR = Path(__file__).resolve().parents[2]` — two levels up from `tests/` points to `plugins/`, which is the correct plugins root.

---

## Common Patterns

- **Adding a new translate flag**: add it in `register_subparsers`, validate in `run()`, add a field to the relevant `PromptSpec`, add the fragment to `translation_fragments.py`, update `prompts.template.toml`.
- **Adding a new language-pair rule**: add an entry to `LANGUAGE_PAIR_NOTES` in `translation_fragments.py`; it is picked up automatically by `TranslationPromptSpec._pair_note()`.
- **Adding a script-specific image OCR hint**: add an entry to `IMAGE_TRANSLATION_SCRIPT_GUIDANCE` keyed by the language name string (e.g. `"Japanese"`).
- **Never** import from `pu_plugin.translation.settings` outside `src/` — use the constants exported from `src.settings` (which resolves to whichever copy is active via sys.modules).

---

## Relationship to Main Repo

This plugin imports the following from the main repo at runtime (not available in this repo alone):
- `src.cli`: `_add_common_flags`, `_add_notes_flags`
- `src.config`: `parse_language_code`, `validate_page_nums`
- `src.errors`: `CLIError`
- `src.models`: `OutputOptions`
- `src.processors.constants`: `IMAGE_EXTENSIONS`
- `src.processors.docx_processor`: `DocxProcessor`
- `src.processors.pdf_processor`: `generate_process_text`
- `src.processors.txt_processor`: `TxtProcessor`
- `src.services.constants`: `DEFAULT_PARALLEL_WORKERS`
- `src.settings`: `DEFAULT_PAGE_SIZE`
- `src.runtime.sandbox_processor`: `SandboxProcessor`

These imports are at module level in `plugin.py` and will fail if the plugin is loaded outside the main repo context. This is expected and by design.

---

## Git Commit Format

Follow the same convention as the main repo:

```
<type>(<scope>): <short summary>   ← imperative mood, ≤ 72 chars

Why:
- <reason>

What changed:
- <change 1>
- <change 2>

Notes:
- <migration/compatibility details if any>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`  
Scope examples: `plugin`, `prompts`, `settings`, `services`, `tests`, `docs`

**Never run `git commit` or `git add`. The user handles all commits.**
