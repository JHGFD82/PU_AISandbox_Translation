# East Asia Translation Plugin — AI Coding Assistant Instructions

## Plugin Overview
This is the East Asia extension for the `translate` command in [PU AI Sandbox](https://github.com/princeton-oit/PU_AISandbox). It adds support for Japanese, Chinese (Simplified/Traditional), and Korean as source languages, and contributes East Asian destination-side guidance when those languages appear as translation targets.

This repo lives at `plugins/translation-ea/` inside the main PU_AISandbox repo. It **requires** the base translation plugin (`plugins/translation/`) to be present — the base plugin owns the service layer. This plugin owns only its fragment registrations, one CLI flag (`--kanbun`), and routing logic.

All `src.*` imports resolve against the main repo's `src/`. The service imports (`src.services.*`) resolve via the base plugin's sys.modules injection, which runs before this plugin loads (alphabetical order guarantee).

---

## Repository Layout

```text
plugin.py                        EastAsiaTranslationPlugin — handles, register_command_flags, get_peer_guidance, run
fragments.py                     EA prompt constants; registers into base plugin's fragment dicts at import time
settings.toml                    Default model parameters (mirrors base plugin defaults)
conftest.py                      Inserts main repo root into sys.path for pytest
pytest.ini                       testpaths=tests, pythonpath=../..
tests/
  ...
```

---

## Dispatch Model

The plugin loader merges this plugin and the base translation plugin into a `DispatchPlugin` (see `src/runtime/dispatch_plugin.py`) because both declare `handles`. DispatchPlugin:
- Routes `translate <lang-code>` to whichever plugin owns the source language
- Calls `get_peer_guidance(dest_token)` on the plugin owning the destination language
- Injects returned guidance into `args._peer_guidance` for the owning plugin's `run()` to consume

This plugin's `run()` must never be called when the base plugin is absent; it checks for `pu_plugin.translation.plugin` in sys.modules and raises CLIError if missing.

---

## Prompt Architecture

### `fragments.py`
Single source of truth for all EA-specific prompt text. Contains constants and dicts registered into the base plugin's fragment dicts (`translation_fragments.LANGUAGE_PAIR_NOTES`, `IMAGE_TRANSLATION_SCRIPT_GUIDANCE`) via `setdefault()` at import time.

Key items:
- `KANBUN_NOTE` — appended to `variant_notes` when `--kanbun` is active
- `_SCRIPT_GUIDANCE` — dict of EA script notes; entries registered into base `IMAGE_TRANSLATION_SCRIPT_GUIDANCE`
- `_PAIR_NOTES` — Japanese↔Korean honorific conventions; entries registered into base `LANGUAGE_PAIR_NOTES`
- `PEER_GUIDANCE` — `{dest_language: note}` returned by `get_peer_guidance()`; empty by default

**`setdefault()` rule**: always use `setdefault()` when registering into the base dicts. This ensures that if two language plugins both provide an entry for the same key, the first-loaded one wins without silent overwrites.

### `variant_notes` pattern
`TranslationService.variant_notes: list[str]` is a list of additional-instructions strings. Each entry is rendered as a separate `ADDITIONAL_INSTRUCTIONS` block in the system prompt, in order. `plugin.py`'s `run()` appends to this list before calling `_base_module._execute_translate()`:
1. `KANBUN_NOTE` if `--kanbun` is active
2. Each entry in `args._peer_guidance` (injected by DispatchPlugin)

---

## `plugin.py` — Key Methods

- `register_command_flags(parser)` — adds `--kanbun` to an *existing* parser (called by DispatchPlugin, not by this plugin's own `register_subparsers`)
- `register_subparsers(subparsers)` — fallback standalone parser (used only if base plugin absent; builds a full parser including all universal flags)
- `get_peer_guidance(token)` — returns `_frags.PEER_GUIDANCE.get(token)` or None
- `run(...)` — checks base module in sys.modules, creates SandboxProcessor, appends variant notes, calls `_base_module._execute_translate()`

---

## Common Patterns

- **Adding a new EA language**: add script guidance to `_SCRIPT_GUIDANCE` in `fragments.py`; add relevant pair notes to `_PAIR_NOTES`; add the full language name to `EastAsiaTranslationPlugin.handles` in `plugin.py`.
- **Adding a new variant flag** (like `--kanbun`): add the fragment constant to `fragments.py`; add the flag in `register_command_flags()`; append the note in `run()` before calling `_execute_translate`.
- **Adding peer guidance for a destination**: add an entry to `PEER_GUIDANCE` in `fragments.py` keyed by the exact full language name.
- **Never** add universal flags (language_code, -i, -o, -w, etc.) to `register_command_flags()` — those belong to the base plugin.
- **Never** call `sandbox.translation_service` directly to set fields other than `variant_notes` — all service wiring lives in `_execute_translate` in the base plugin.

---

## Relationship to Main Repo and Base Plugin

Runtime dependencies (from main repo `src/`):
- `src.cli`: `_add_common_flags`, `_add_notes_flags`
- `src.config`: `parse_language_code`
- `src.errors`: `CLIError`
- `src.runtime.sandbox_processor`: `SandboxProcessor`

Via base plugin sys.modules injection (available because base loads first):
- `src.services.translation_service`: `TranslationService`
- `src.services.image_translation_service`: `ImageTranslationService`
- `src.services.prompts.translation_fragments`: fragment dicts for `setdefault()` registration

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
Scope examples: `plugin`, `fragments`, `settings`, `tests`, `docs`

**Never run `git commit` or `git add`. The user handles all commits.**
