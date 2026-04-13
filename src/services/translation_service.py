"""Translation service for the PU AI Sandbox."""

import logging
import re
import time
from collections import deque
from typing import Any, List, Optional, Iterable
from itertools import islice
from tqdm import tqdm

from pdfminer.pdfpage import PDFPage

from ..models import (
    resolve_model, get_model_system_role,
    maybe_sync_model_pricing, get_model_max_completion_tokens,
    OutputOptions,
)
from .api_errors import APISignal
from .base_service import BaseService
from ..output.file_output import FileOutputHandler
from ..processors.pdf_processor import PDFProcessor, generate_process_text, detect_numbered_content
from ..tracking.token_tracker import TokenTracker
from .constants import PAGE_DELAY_SECONDS

# Translation API parameters
TRANSLATION_TEMPERATURE: float = 0.5
TRANSLATION_MAX_TOKENS: int = 4000  # Large enough for academic content with footnotes
TRANSLATION_TOP_P: float = 0.5

# Fraction of the previous page passed as context to the next translation call
CONTEXT_PERCENTAGE: float = 0.65

# Regex pattern for matching citation/reference numbers in CJK and ASCII brackets
_CITATION_NUM_RE: str = r'[（\(](\d+)[）\)]'


class TranslationService(BaseService):
    """Handles translation operations using PortKey API."""

    def __init__(self, api_key: str, professor: Optional[str] = None, token_tracker: Optional[TokenTracker] = None, token_tracker_file: Optional[str] = None, model: Optional[str] = None, temperature: Optional[float] = None, top_p: Optional[float] = None, max_tokens: Optional[int] = None):
        super().__init__(api_key, professor, token_tracker, token_tracker_file, model, temperature, top_p, max_tokens)
        self.pdf_processor = PDFProcessor()
    
    def _get_model(self) -> str:
        """Get the model to use, preferring custom model if specified."""
        model = resolve_model(requested_model=self.custom_model)
        maybe_sync_model_pricing(model)
        return model

    def _call_translation_api(self, model: str, system_role: str,
                               system_prompt: str, user_prompt: str) -> Any:
        """Call the translation API with the correct token-limit parameter for the model."""
        temperature = self.custom_temperature if self.custom_temperature is not None else TRANSLATION_TEMPERATURE
        top_p = self.custom_top_p if self.custom_top_p is not None else TRANSLATION_TOP_P
        if self.custom_temperature is not None or self.custom_top_p is not None:
            logging.debug(f"Translation API params: temperature={temperature}, top_p={top_p}")
        messages = [
            {"role": system_role, "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        max_tokens = self.custom_max_tokens if self.custom_max_tokens is not None else get_model_max_completion_tokens(model, TRANSLATION_MAX_TOKENS)
        return self._create_completion(
            model, messages, max_tokens,
            temperature=temperature, top_p=top_p,
        )
    
    def _create_translation_prompt(self, source_language: str, target_language: str, output_format: str = "console", text: str = "") -> tuple[str, str]:
        """Create system and user prompt templates for translation."""
        
        has_numbered = detect_numbered_content(text) if text else False
        logging.debug(f"Numbered content detected: {has_numbered}")

        formatting_instruction = self._get_formatting_instruction(output_format)
        numbered_content_instruction = self._get_numbered_content_instruction() if has_numbered else ""
        
        system_prompt = self._build_system_prompt(
            source_language, target_language, formatting_instruction, numbered_content_instruction
        )
        
        user_prompt_template = self._build_user_prompt_template(source_language, target_language, has_numbered)

        if self.system_note:
            system_prompt += f"\n\nADDITIONAL INSTRUCTIONS:\n{self.system_note}"
        if self.user_note:
            user_prompt_template += f"ADDITIONAL NOTES:\n{self.user_note}\n\n"

        return system_prompt, user_prompt_template
    
    def _get_formatting_instruction(self, output_format: str) -> str:
        """Get formatting instructions based on output format."""
        if output_format.lower() in ["pdf", "txt", "file", "docx"]:
            return (
                "Use proper paragraph breaks and standard text formatting suitable for file output. "
                "Use actual line breaks (not \\n characters) to separate paragraphs and sections naturally."
            )
        else:  # console output
            return 'You can format and line break the output yourself using "\\n" for line breaks in console output.'
    
    def _get_numbered_content_instruction(self) -> str:
        """Get comprehensive instructions for handling numbered content."""
        return """IMPORTANT: Pay special attention to numbered lists, citations, and footnotes.
Preserve ALL numbering exactly as it appears in the source text. This includes:
• Arabic numerals: 1, 2, 3... or 1), 2), 3)...
• Numbers in brackets: [1], [2], [3]... or (1), (2), (3)...
• Chinese numerals: 一、二、三... or （一）、（二）、（三）...
• Japanese/Korean numbering: ①, ②, ③... or １、２、３...
• Japanese reference format: 14　author「title」→ should become "14. Author, 'Title'"

CRITICAL DISTINCTION - DO NOT ADD NUMBERING:

- If the source text has section headings WITHOUT numbers, do NOT add numbers to them
- Only preserve numbering that already exists in the source
- Section titles like "背景" or "結論" should remain as "Background" or "Conclusion" without numbers

CRITICAL FOR BIBLIOGRAPHY/REFERENCES: If you encounter numbered reference lists or bibliography 
(like "1. Author Title, Publisher" format), preserve the exact numbering format. Do NOT convert 
numbered references into paragraph form. Keep each reference as a separate numbered item.

CRITICAL: When you see Japanese reference format like "14　松下安雄監修樋垣元良「福岡藩」", 
translate it to proper English reference format like "14. Supervised by Matsushita Yasuo, Higaki Motoyoshi, 'Fukuoka Domain'". 
DO NOT output just the number "14" by itself - always include the full reference text with proper formatting."""
    
    def _build_system_prompt(self, source_language: str, target_language: str, 
                           formatting_instruction: str, numbered_content_instruction: str) -> str:
        """Build the complete system prompt."""
        return f"""Follow the instructions carefully. Please act as a professional translator from {source_language} 
to {target_language}. I will provide you with text from a document, and your task is 
to translate it from {source_language} to {target_language}. Please only output the translation and do not 
output any irrelevant content. If there are garbled characters or other non-standard text 
content, delete the garbled characters.

{formatting_instruction}

{numbered_content_instruction}

You may be provided with "--Context: " which includes either the document's abstract or 
text from the previous page for context. You will also be provided with "--Current Page: " 
which includes the text of the current page. Only output the {target_language} translation of 
the "--Current Page: ". Do not output the context, nor the "--Context: " and "--Current Page: " 
labels."""
    
    def _build_user_prompt_template(self, source_language: str, target_language: str, has_numbered: bool = False) -> str:
        """Build the user prompt template."""
        numbered_sections = ""
        if has_numbered:
            numbered_sections = f"""\nCRITICAL: Preserve all numbering systems exactly as they appear in the source (1, 2, 3... or [1], [2]... or ①, ②... etc.).
DO NOT ADD numbering to headings or sections that are not numbered in the source text.

CRITICAL FOR REFERENCES: When translating reference entries like "14　松下安雄監修樋垣元良「福岡藩」", 
translate the COMPLETE reference including author names, titles, and formatting. Output should be 
"14. Author Name, 'Title'" NOT just the isolated number "14". Always translate the full reference text.

NUMBERING CONTINUATION - VERY IMPORTANT: 
- If the context shows "Previous numbering ended with: X. Reference", you MUST continue numbering from X+1 for any new numbered items on the current page.
- Do NOT restart numbering from 1 - always continue the sequence from the previous page.
- Example: If context shows "Previous numbering ended with: 25. Some Reference", and current page has more numbered items, they should be numbered 26, 27, 28, etc.
- This applies ONLY to numbered reference lists, NOT to section headings.

SECTION HEADINGS: If the source has section headings without numbers, translate them as headings without adding numbers.
"""

        return f"""Translate only the {source_language} text of the "--Current Page: " to {target_language}, without outputting any other 
content, and without outputting anything related to "--Context: ", if provided.
{numbered_sections}
IMPORTANT: Only add a "Footnotes:" section if there is actual explanatory footnote text at the bottom 
of the page. Do NOT add "Footnotes:" for simple citation numbers like (38), (39) within paragraphs.

Do not provide any prompts to the user, for example: "This is the translation of the current page.":

"""
    
    def build_prompts(self, text: str, source_language: str, target_language: str, output_format: str = "console") -> tuple[str, str]:
        """Return (system_prompt, user_prompt) for the given text without calling the API.

        Used by --dry-run mode to preview what would be sent to the model.
        """
        system_prompt, user_prompt_template = self._create_translation_prompt(source_language, target_language, output_format, text)
        return system_prompt, user_prompt_template + text

    def translate_text(self, text: str, source_language: str, target_language: str, output_format: str = "console") -> "str | APISignal":
        """Translate text using the specified model with retry logic for content filters."""
        model = self._get_model()
        system_prompt, user_prompt_template = self._create_translation_prompt(source_language, target_language, output_format, text)
        user_prompt = user_prompt_template + text

        def body(attempt: int) -> Any:
            logging.debug(f'Making API call to model: {model}')
            system_role = get_model_system_role(model)
            response = self._call_translation_api(model, system_role, system_prompt, user_prompt)
            self._record_response_usage(response, model)
            if response.choices and len(response.choices) > 0 and response.choices[0].message:
                content = response.choices[0].message.content
                if content is not None and isinstance(content, str):
                    print("\n" + content)
                    return content
                return None  # content was None or wrong type — retry
            print("\n[No content returned by the model]")
            logging.warning('No content returned by the model.')
            return ""  # terminal empty result

        return self._run_with_retry(
            body, model, "translation",
            timeout_msg="Translation returned no content after maximum retries.",
            return_signal_on_error=True,
        )
    
    @staticmethod
    def _resolve_output_format(opts: OutputOptions) -> str:
        """Derive the output format string from the requested output file path and auto-save flag."""
        if opts.output_file:
            ext = opts.output_file.lower().rsplit('.', 1)[-1] if '.' in opts.output_file else ''
            format_map = {'pdf': 'pdf', 'docx': 'docx', 'txt': 'txt'}
            return format_map.get(ext, 'file')
        if opts.auto_save:
            return 'txt'
        return 'console'

    def translate_page_text(self, abstract_text: str, page_text: str, previous_page: str, 
                          source_language: str, target_language: str, output_format: str = "console",
                          previous_translated: str = "") -> str:
        """Translate page text with context."""
        process_text = generate_process_text(abstract_text, page_text, previous_page, CONTEXT_PERCENTAGE, previous_translated)
        return self.translate_text(process_text, source_language, target_language, output_format)

    @staticmethod
    def _find_split_point(text: str, middle_index: int) -> int:
        """Find a natural split point near the middle of text.

        Prefers a double-newline paragraph boundary, then any sentence-ending
        punctuation. Falls back to the raw middle index if neither is found.
        """
        # Prefer a paragraph break within ±100 chars of the middle
        for offset in range(100):
            for candidate in (middle_index + offset, middle_index - offset):
                if 0 < candidate < len(text) and text[candidate:candidate + 2] == '\n\n':
                    return candidate + 2

        # Fall back to a sentence boundary within ±50 chars
        for offset in range(50):
            for candidate in (middle_index + offset, middle_index - offset):
                if 0 < candidate < len(text) and text[candidate] in '.!?。':
                    return candidate + 1

        return middle_index

    def generate_text(self, abstract_text: str, page_text: str, previous_page: str, 
                     page_num: int, source_language: str, target_language: str, output_format: str = "console", 
                     previous_translated: str = "") -> str:
        """Generate translated text for a page, handling context length limits."""
        result: list[str] = []
        parts_to_translate: deque[str] = deque([page_text])
        
        # Debug logging
        logging.debug(f"Starting translation of page {page_num + 1}, original text length: {len(page_text)} chars")
        
        # Check for numbered citations in the original text
        citation_numbers = re.findall(_CITATION_NUM_RE, page_text)
        if citation_numbers:
            logging.debug(f"Page {page_num + 1} contains citation numbers: {citation_numbers}")

        while parts_to_translate:
            # Use popleft() to ensure FIFO processing - translate parts in the correct order
            current_part = parts_to_translate.popleft()
            logging.debug(f"Translating part {len(result) + 1} of page {page_num + 1}, length: {len(current_part)} chars")
            
            translated_text = self.translate_page_text(
                abstract_text, current_part, previous_page, source_language, target_language, output_format, previous_translated
            )

            if translated_text == APISignal.CONTEXT_LENGTH_EXCEEDED:
                # Split the text in half and add to FRONT of queue to maintain order
                middle_index = len(current_part) // 2
                split_point = self._find_split_point(current_part, middle_index)

                first_half = current_part[:split_point].strip()
                second_half = current_part[split_point:].strip()
                
                # Prepend in reverse order so first_half ends up at the front
                if second_half:
                    parts_to_translate.appendleft(second_half)
                if first_half:
                    parts_to_translate.appendleft(first_half)
                    
                logging.warning(f"Context length exceeded on page {page_num + 1}, split into {len([p for p in [first_half, second_half] if p])} parts")
                
            elif translated_text == APISignal.CONTENT_FILTER:
                result.append(f"\n***Content filter triggered on page {page_num + 1} - text skipped***\n")
                logging.error(f"Content filter triggered on page {page_num + 1}")
            elif translated_text == '':
                result.append(f"\n***Translation error on page {page_num + 1}.***\n")
                logging.error(f"Translation returned empty result on page {page_num + 1}")
            else:
                result.append(translated_text)
                logging.debug(f"Successfully translated part {len(result)} of page {page_num + 1}, output length: {len(translated_text)} chars")
                
                # Check if numbered citations were preserved in translation
                translated_numbers = re.findall(_CITATION_NUM_RE, translated_text)
                if translated_numbers:
                    logging.debug(f"Part {len(result)} of page {page_num + 1} contains translated numbers: {translated_numbers}")

        final_result = f"\n\n-- Page {page_num + 1} -- \n\n" + "\n".join(result)
        logging.debug(f"Completed translation of page {page_num + 1}, final length: {len(final_result)} chars")
        return final_result

    def _make_pdf_triples(
        self,
        pages: Iterable[PDFPage],
        start_page: int,
    ) -> Iterable[tuple[int, str, str]]:
        """Yield (index, page_text, previous_page_text) for each PDF page."""
        page_text = ""
        for i, page in enumerate(pages, start=start_page):
            previous_page = page_text
            page_text = self.pdf_processor.process_page(page)
            yield i, page_text, previous_page

    @staticmethod
    def _make_text_triples(
        text_pages: List[str],
    ) -> Iterable[tuple[int, str, str]]:
        """Yield (index, page_text, previous_page_text) for each pre-extracted text page."""
        previous_page = ""
        for i, page_text in enumerate(text_pages):
            yield i, page_text, previous_page
            previous_page = page_text

    def _translate_page_sequence(
        self,
        page_triples: Iterable[tuple[int, str, str]],
        abstract_text: str,
        source_language: str,
        target_language: str,
        output_format: str,
        first_index: int,
        unit_label: str,
        opts: OutputOptions,
        input_file_path: Optional[str],
    ) -> List[str]:
        """Translate a sequence of (index, page_text, previous_page) triples.

        Shared by translate_document and translate_text_pages.
        """
        document_text: list[str] = []
        progressive_output_path: Optional[str] = None
        previous_translated = ""

        for i, page_text, previous_page in tqdm(page_triples, desc="Translating... ", ascii=True):
            try:
                translated_text = self.generate_text(
                    abstract_text, page_text, previous_page, i,
                    source_language, target_language, output_format, previous_translated
                )
                document_text.append(translated_text)
                previous_translated = translated_text

                if i > first_index:
                    time.sleep(PAGE_DELAY_SECONDS)

                if opts.progressive_save and (opts.output_file or opts.auto_save):
                    progressive_output_path = FileOutputHandler.save_page_progressively(
                        translated_text,
                        input_file_path,
                        opts.output_file,
                        opts.auto_save,
                        source_language,
                        target_language,
                        is_first_page=(i == first_index),
                    )

            except Exception as e:
                error_message = f"\n***Translation error on {unit_label} {i + 1}: {e}***\n"
                document_text.append(error_message)
                print(f"Error on {unit_label} {i + 1}: {e}")

                if opts.progressive_save and (opts.output_file or opts.auto_save):
                    FileOutputHandler.save_page_progressively(
                        error_message,
                        input_file_path,
                        opts.output_file,
                        opts.auto_save,
                        source_language,
                        target_language,
                        is_first_page=(i == first_index),
                    )
                continue

        if opts.progressive_save and progressive_output_path:
            print(f"\nProgressive translation saved to: {progressive_output_path}")

        return document_text

    def translate_document(self, pages: Iterable[PDFPage], abstract_text: Optional[str],
                           start_page: int, end_page: Optional[int],
                           source_language: str, target_language: str,
                           opts: OutputOptions = OutputOptions(),
                           input_file_path: Optional[str] = None) -> List[str]:
        """Translate all pages in a document."""
        output_format = self._resolve_output_format(opts)
        pages = islice(pages, start_page, None if end_page is None else end_page + 1)
        return self._translate_page_sequence(
            self._make_pdf_triples(pages, start_page),
            abstract_text=abstract_text or '',
            source_language=source_language,
            target_language=target_language,
            output_format=output_format,
            first_index=start_page,
            unit_label='page',
            opts=opts,
            input_file_path=input_file_path,
        )
    
    def translate_text_pages(self, text_pages: List[str], abstract_text: Optional[str],
                            source_language: str, target_language: str,
                            opts: OutputOptions = OutputOptions(),
                            input_file_path: Optional[str] = None) -> List[str]:
        """Translate pre-extracted text pages (e.g., from Word documents)."""
        output_format = self._resolve_output_format(opts)
        return self._translate_page_sequence(
            self._make_text_triples(text_pages),
            abstract_text=abstract_text or '',
            source_language=source_language,
            target_language=target_language,
            output_format=output_format,
            first_index=0,
            unit_label='section',
            opts=opts,
            input_file_path=input_file_path,
        )
