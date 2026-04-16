"""Prompt spec for translation operations."""

from dataclasses import dataclass
from typing import Optional

from . import fragments as F


@dataclass
class TranslationPromptSpec:
    """Parameters for a translation prompt pair.

    Call system_prompt() and user_prompt() to obtain the final strings.
    """

    source_language: str
    target_language: str
    output_format: str = "console"
    has_numbered: bool = False
    kanbun: bool = False
    system_note: Optional[str] = None
    user_note: Optional[str] = None

    def _formatting_fragment(self) -> str:
        key = "file" if self.output_format.lower() in ("pdf", "txt", "file", "docx") else "console"
        return F.TRANSLATION_FORMATTING[key]

    def _pair_note(self) -> str:
        return F.LANGUAGE_PAIR_NOTES.get((self.source_language, self.target_language), "")

    def system_prompt(self) -> str:
        sections = [
            F.TRANSLATION_ROLE.format(source=self.source_language, target=self.target_language),
            self._formatting_fragment(),
        ]
        if self.has_numbered:
            sections.append(F.TRANSLATION_NUMBERED_SYSTEM)
        sections.append(F.TRANSLATION_CONTEXT_SPEC.format(target=self.target_language))
        pair_note = self._pair_note()
        if pair_note:
            sections.append(F.ADDITIONAL_INSTRUCTIONS.format(note=pair_note))
        if self.kanbun:
            sections.append(F.ADDITIONAL_INSTRUCTIONS.format(note=F.KANBUN_NOTE))
        if self.system_note:
            sections.append(F.ADDITIONAL_INSTRUCTIONS.format(note=self.system_note))
        return "\n\n".join(sections)

    def user_prompt(self) -> str:
        parts = [
            F.TRANSLATION_USER_BASE.format(
                source=self.source_language, target=self.target_language
            )
        ]
        if self.has_numbered:
            parts.append(F.TRANSLATION_NUMBERED_USER)
        parts.append(F.TRANSLATION_FOOTNOTE_RULE)
        parts.append(F.TRANSLATION_NO_META_COMMENTARY)
        if self.user_note:
            parts.append(F.ADDITIONAL_NOTES.format(note=self.user_note))
        # Trailing newline preserved for backward compatibility: the caller
        # concatenates the source text directly onto the end of this string.
        return "\n\n".join(parts) + "\n\n"
