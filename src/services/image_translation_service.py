"""Combined OCR + translation service — single vision prompt resolves ambiguous characters using translation context."""

import logging
import re
import time
from typing import Any, Optional

from ..models import (
    get_model_system_role, model_supports_vision, get_vision_capable_models,
    get_model_max_completion_tokens, resolve_model, get_default_model,
)
from .api_errors import APISignal, classify_api_error
from .base_service import BaseService
from ..processors.image_processor import ImageProcessor
from ..tracking.token_tracker import TokenTracker
from .constants import MAX_RETRIES, BASE_RETRY_DELAY, IMAGE_TRANSLATION_SCRIPT_GUIDANCE

# Combined OCR + translation token budget
IMAGE_TRANSLATION_MAX_TOKENS: int = 8000  # Overridden per-model via max_completion_tokens in catalog


class ImageTranslationService(BaseService):
    """Handles combined OCR + translation from images in a single API call.

    Designed for reasoning-capable vision models (e.g. gpt-5) that can hold
    both transcription and translation in context simultaneously, resolving
    ambiguous characters using translation context rather than guessing during
    a separate OCR pass.

    Returns both a transcript and a translation so the caller can present or
    save either or both.
    """

    def __init__(
        self,
        api_key: str,
        professor: Optional[str] = None,
        token_tracker: Optional[TokenTracker] = None,
        token_tracker_file: Optional[str] = None,
        model: Optional[str] = None,
    ):
        super().__init__(api_key, professor, token_tracker, token_tracker_file, model)
        self.image_processor = ImageProcessor()

    def _get_model(self) -> str:
        """Get model to use, preferring the catalog image_translation default."""
        img_trans_default = get_default_model("image_translation")
        model = resolve_model(
            requested_model=self.custom_model,
            prefer_model=img_trans_default,
            require_vision=True,
        )
        if not self.custom_model and model != img_trans_default:
            logging.warning(
                f"Preferred image translation model '{img_trans_default}' not available. "
                f"Using '{model}' instead."
            )
        return model

    def _get_max_tokens(self, model: str) -> int:
        """Get token budget for this model, using per-model catalog override if set."""
        return get_model_max_completion_tokens(model, IMAGE_TRANSLATION_MAX_TOKENS)

    def _build_system_prompt(self, source_language: str, target_language: str, vertical: bool = False) -> str:
        script_note = IMAGE_TRANSLATION_SCRIPT_GUIDANCE.get(source_language, "")
        script_section = f"\nSCRIPT NOTES:\n{script_note}\n" if script_note else ""
        vertical_section = (
            "\nTEXT ORIENTATION:\n"
            "The majority of text in this image is vertical — written top-to-bottom, "
            "with columns ordered right-to-left. Read each column from top to bottom, "
            "proceeding from the rightmost column to the leftmost.\n"
        ) if vertical else ""
        return f"""You are an expert reader and translator specialising in {source_language} text found in images.
{script_section}{vertical_section}
Your task is to perform two operations on the image:
1. TRANSCRIBE all visible {source_language} text exactly as it appears.
2. TRANSLATE that transcribed text into fluent, accurate {target_language}.

You MUST return your response in EXACTLY this format, with the section headers on their own lines:

[TRANSCRIPT]
<transcribed {source_language} text, preserving original layout and line breaks>

[TRANSLATION]
<{target_language} translation of the transcribed text>

TRANSCRIPTION RULES:
- Reproduce text exactly as it appears in the image — do not correct, modernise, or alter characters.
- Preserve line breaks, punctuation, numbering, and overall structure.
- Use surrounding context and translation target to resolve ambiguous or partially obscured characters; \
mark genuinely unreadable text with [unclear] inline rather than a trailing summary.
- Do not skip any text, including headers, captions, inscriptions, or marginal notes.

TRANSLATION RULES:
- Produce a fluent, scholarly {target_language} translation.
- Preserve the structure of the original (line breaks, stanzas, numbered items, etc.).
- For classical or archaic language, prefer a literary translation over a literal one.
- Do not add explanatory notes, commentary, or translator remarks."""

    def _build_user_prompt(self, source_language: str, target_language: str, vertical: bool = False) -> str:
        vertical_note = " The text is predominantly vertical (top-to-bottom, right-to-left columns)." if vertical else ""
        return (
            f"Transcribe all visible {source_language} text from this image exactly as it appears,"
            f"{vertical_note} then translate it to {target_language}."
        )

    def build_prompts(self, source_language: str, target_language: str, vertical: bool = False) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) without calling the API.

        Used by --dry-run mode to preview what would be sent to the model.
        """
        system_prompt = self._build_system_prompt(source_language, target_language, vertical=vertical)
        user_prompt = self._build_user_prompt(source_language, target_language, vertical=vertical)

        if self.system_note:
            system_prompt += f"\n\nADDITIONAL INSTRUCTIONS:\n{self.system_note}"
        if self.user_note:
            user_prompt += f"\n\nADDITIONAL NOTES:\n{self.user_note}"

        return system_prompt, user_prompt

    def _call_api(
        self,
        model: str,
        system_role: str,
        system_prompt: str,
        user_prompt: str,
        data_url: str,
        max_tokens: int,
    ) -> Any:
        """Call the API with parameters appropriate for the given model."""
        messages: list[dict[str, Any]] = [
            {"role": system_role, "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]
        return self._create_completion(model, messages, max_tokens, temperature=0.3)

    def _parse_response(self, content: str) -> tuple[str, str]:
        """Extract [TRANSCRIPT] and [TRANSLATION] sections from the model response.

        Falls back to treating the full response as the translation if the
        expected section headers are absent.
        """
        transcript_match = re.search(
            r"\[TRANSCRIPT\](.*?)(?=\[TRANSLATION\]|\Z)", content, re.DOTALL
        )
        translation_match = re.search(r"\[TRANSLATION\](.*)", content, re.DOTALL)

        transcript = transcript_match.group(1).strip() if transcript_match else ""
        translation = translation_match.group(1).strip() if translation_match else ""

        if not transcript and not translation:
            logging.warning(
                "Could not parse [TRANSCRIPT]/[TRANSLATION] sections from response; "
                "treating full response as translation."
            )
            translation = content.strip()

        return transcript, translation

    def process_image_translation(
        self,
        file_path: str,
        source_language: str,
        target_language: str,
        vertical: bool = False,
    ) -> tuple[str, str]:
        """Transcribe and translate an image in a single API call.

        Args:
            file_path: Absolute path to the image file.
            source_language: Language of text in the image (e.g. 'Chinese').
            target_language: Language to translate into (e.g. 'English').
            vertical: Whether the text is predominantly vertical (top-to-bottom, right-to-left).

        Returns:
            (transcript, translation) — either may be empty if parsing fails.

        Raises:
            ValueError: If the selected model does not support vision.
            RuntimeError: If no valid response is received after all retries.
        """
        model = self._get_model()

        if not model_supports_vision(model):
            vision_models = get_vision_capable_models()
            raise ValueError(
                f"Model '{model}' does not support image processing. "
                f"Vision-capable models: {vision_models}"
            )

        system_role = get_model_system_role(model)
        system_prompt, user_prompt = self.build_prompts(source_language, target_language, vertical=vertical)
        max_tokens = self._get_max_tokens(model)

        try:
            data_url = self.image_processor.local_image_to_data_url(file_path)
        except Exception as e:
            logging.error(f"Failed to read image {file_path}: {e}")
            raise

        for attempt in range(MAX_RETRIES):
            try:
                if attempt > 0:
                    delay = BASE_RETRY_DELAY * (2 ** attempt) + (0.1 * attempt)
                    logging.info(
                        f"Retrying image translation "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}) after {delay:.1f}s..."
                    )
                    time.sleep(delay)

                logging.info(
                    f"Making image translation API call to model: {model} "
                    f"(system role: {system_role}, max_tokens: {max_tokens})"
                )
                response = self._call_api(
                    model, system_role, system_prompt, user_prompt, data_url, max_tokens
                )
                self._record_response_usage(response, model, critical=True)

                if (
                    response.choices
                    and len(response.choices) > 0
                    and response.choices[0].message
                ):
                    content = response.choices[0].message.content
                    if content is None:
                        logging.warning(
                            f"Response content is None. "
                            f"Raw message: {response.choices[0].message}"
                        )
                        continue
                    if not isinstance(content, str):
                        logging.warning(
                            f"Unexpected content type {type(content)}: {content!r}. Retrying..."
                        )
                        continue
                    if not content.strip():
                        logging.warning(
                            f"Empty response (attempt {attempt + 1}/{MAX_RETRIES}). Retrying..."
                        )
                        continue
                    return self._parse_response(content)
                else:
                    logging.warning("No choices in API response. Retrying...")
                    continue

            except Exception as e:
                signal = classify_api_error(e, model)
                if signal == APISignal.CONTENT_FILTER and attempt < MAX_RETRIES - 1:
                    logging.warning(
                        f"Content filter triggered "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}). Retrying..."
                    )
                    continue
                logging.error(f"API error: {e}")
                raise

        raise RuntimeError(
            "Image translation returned no content after maximum retries — "
            "check model response format in debug logs."
        )
