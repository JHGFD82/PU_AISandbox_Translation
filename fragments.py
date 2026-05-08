"""East Asia translation prompt fragments.

Loaded by plugins/translation-ea/plugin.py at import time.  Populates the
base translation plugin's mutable fragment registries with East Asia language
data, then exposes EA-specific constants for use in plugin.py's run().

REGISTRATION PATTERN
--------------------
Each dict uses ``setdefault()`` rather than direct assignment, so that user
overrides already applied by the base plugin's ``_load_user_overrides()``
(which runs when translation_fragments.py is first imported) are respected.
If a user has placed a Japanese→Korean entry in prompts.toml, it stays; if
not, the EA default is used.

ADDING A NEW LANGUAGE
---------------------
To add a new East Asian language:
  1. Add its script guidance to _SCRIPT_GUIDANCE.
  2. Add any relevant language-pair notes to _PAIR_NOTES.
  3. Add it to EastAsiaTranslationPlugin.handles in plugin.py.
No changes to the base plugin or the framework are needed.
"""

from src.services.prompts import translation_fragments as _F  # noqa: E402


# ── Image translation script guidance ─────────────────────────────────────────
# Registered into the base module's IMAGE_TRANSLATION_SCRIPT_GUIDANCE dict.

_SCRIPT_GUIDANCE: dict[str, str] = {
    "Chinese": (
        "The source text uses Chinese characters (hanzi/漢字). "
        "Transcribe each character exactly as it appears."
    ),
    "Simplified Chinese": (
        "The source text uses Simplified Chinese characters (简体字). "
        "Transcribe each character exactly in its simplified form — "
        "do NOT convert to or substitute traditional variants."
    ),
    "Traditional Chinese": (
        "The source text uses Traditional Chinese characters (繁體字). "
        "Transcribe each character exactly in its traditional form — "
        "do NOT convert to or substitute simplified variants."
    ),
    "Japanese": (
        "The source text uses Japanese script, which combines kanji (Chinese-derived characters), "
        "hiragana, katakana, and possibly rōmaji. "
        "Reproduce all scripts exactly as written. "
        "Some kanji may be Japanese-specific forms (kokuji) not found in standard Chinese — "
        "transcribe them faithfully and do NOT substitute simplified or traditional Chinese variants. "
        "Use kanji ambiguity resolution via translation context before committing to a transcript."
    ),
    "Korean": (
        "The source text uses Korean script (hangul/한글), possibly mixed with hanja (漢字) or Latin text. "
        "Transcribe all scripts exactly as they appear."
    ),
}

for _lang, _note in _SCRIPT_GUIDANCE.items():
    _F.IMAGE_TRANSLATION_SCRIPT_GUIDANCE.setdefault(_lang, _note)


# ── Language-pair notes ────────────────────────────────────────────────────────
# Registered into the base module's LANGUAGE_PAIR_NOTES dict.

_PAIR_NOTES: dict[tuple[str, str], str] = {
    ("Japanese", "Korean"): (
        "Japanese and Korean both have elaborate honorific systems that do not map "
        "one-to-one. Apply the following conventions:\n"
        "- Preserve the formality register of the source: formal/polite text should "
        "become formal/polite in the target (e.g. 합쇼체 or 해요체 in Korean; "
        "丁寧語 / teineigo in Japanese).\n"
        "- Translate title suffixes appropriately: Japanese 様/さん/先生 → Korean "
        "님/선생님, and vice versa.\n"
        "- Do not flatten honorific speech to plain speech (반말 / タメ口) unless "
        "the source explicitly uses an informal register."
    ),
    ("Korean", "Japanese"): (
        "Korean and Japanese both have elaborate honorific systems that do not map "
        "one-to-one. Apply the following conventions:\n"
        "- Preserve the formality register of the source: formal/polite text should "
        "become formal/polite in the target (丁寧語 / teineigo in Japanese; "
        "합쇼체 or 해요체 in Korean).\n"
        "- Translate title suffixes appropriately: Korean 님/선생님 → Japanese "
        "様/さん/先生, and vice versa.\n"
        "- Do not flatten honorific speech to plain speech (タメ口 / 반말) unless "
        "the source explicitly uses an informal register."
    ),
}

for _pair, _note in _PAIR_NOTES.items():
    _F.LANGUAGE_PAIR_NOTES.setdefault(_pair, _note)


# ── Variant notes ──────────────────────────────────────────────────────────────
# Appended to TranslationService.variant_notes by plugin.py's run() when the
# corresponding CLI flag is active.

KANBUN_NOTE = (
    "The source text is kanbun (漢文) — Classical Chinese written for Japanese "
    "kundoku (訓読) reading. Apply the following conventions:\n"
    "- Reconstruct word order according to kundoku conventions: Japanese verb-final "
    "syntax, not the Subject-Verb-Object order of Classical Chinese.\n"
    "- Expand implicit grammatical elements (particles, verb endings, auxiliary "
    "words) that are absent in the kanbun but required by kundoku reading.\n"
    "- Preserve kanbun punctuation markers (返り点 kaeriten, 送り仮名 okurigana) "
    "as context clues — do not reproduce them literally in the translation.\n"
    "- Use the register appropriate to classical Japanese scholarly prose when "
    "producing Japanese output, or fluent academic prose for English output.\n"
    "- Proper nouns, reign names, and place names should follow established "
    "Sinological or Japanese historical conventions (e.g. Heian, not 'Hei-an')."
)


# ── Peer guidance ──────────────────────────────────────────────────────────────
# Returned by EastAsiaTranslationPlugin.get_peer_guidance() when one of the
# owned languages appears as a translation *destination* (rather than source).
# Add entries here to inject destination-side conventions into the source
# plugin's prompt when translating INTO an EA language.

PEER_GUIDANCE: dict[str, str] = {
    # Example (uncomment and expand as needed):
    # "Japanese": (
    #     "The translation target is Japanese. Use natural sentence-final forms "
    #     "appropriate to the register of the source text."
    # ),
}
