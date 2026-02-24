"""
Translation service for the CJK Translation script.
"""

import logging
import time
from typing import List, Optional, Iterable
from collections.abc import Iterator as ABCIterator
from itertools import islice
from tqdm import tqdm

from portkey_ai import Portkey
from pdfminer.pdfpage import PDFPage

from ..config import (
    resolve_model, TRANSLATION_TEMPERATURE, TRANSLATION_MAX_TOKENS, TRANSLATION_TOP_P, CONTEXT_PERCENTAGE,
    PAGE_DELAY_SECONDS, MAX_RETRIES, BASE_RETRY_DELAY, extract_page_nums
)
from ..processors.pdf_processor import PDFProcessor, generate_process_text
from ..tracking.token_tracker import TokenTracker


class TranslationService:
    """Handles translation operations using PortKey API."""
    
    def __init__(self, api_key: str, professor: Optional[str] = None, token_tracker: Optional[TokenTracker] = None, token_tracker_file: Optional[str] = None, model: Optional[str] = None):
        """Initialize translation service.
        
        Args:
            api_key: PortKey API key
            professor: Professor name for token tracking
            token_tracker: Shared TokenTracker instance
            token_tracker_file: Custom token tracker file path
            model: Optional model name to use instead of default
        """
        self.api_key = api_key
        self.professor = professor
        self.custom_model = model  # Store custom model if provided
        self.client = Portkey(
            api_key=api_key
        )
        self.pdf_processor = PDFProcessor()
        # Use provided token tracker or create new one
        self.token_tracker = token_tracker if token_tracker is not None else TokenTracker(professor=professor, data_file=token_tracker_file)
    
    def _get_model(self) -> str:
        """Get the model to use, preferring custom model if specified."""
        return resolve_model(requested_model=self.custom_model)
    
    def _create_translation_prompt(self, source_language: str, target_language: str, output_format: str = "console") -> tuple[str, str]:
        """Create system and user prompt templates for translation."""
        
        formatting_instruction = self._get_formatting_instruction(output_format)
        numbered_content_instruction = self._get_numbered_content_instruction()
        
        system_prompt = self._build_system_prompt(
            source_language, target_language, formatting_instruction, numbered_content_instruction
        )
        
        user_prompt_template = self._build_user_prompt_template(source_language, target_language)
        
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
DO NOT output just the number "14" by itself - always include the full reference text with proper formatting.

IMPORTANT DISTINCTION: Only add a "Footnotes:" section if there are actual footnotes - 
meaning separate explanatory text at the bottom of the page that corresponds to numbered markers. 
Do NOT add "Footnotes:" for simple in-text citation numbers like (38), (39) that appear within paragraphs 
without corresponding explanatory text at the bottom. These are just citations, not footnotes. 
Only use "Footnotes:" when there is clearly separate footnote text at the end of the content."""
    
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
    
    def _build_user_prompt_template(self, source_language: str, target_language: str) -> str:
        """Build the user prompt template."""
        return f"""Translate only the {source_language} text of the "--Current Page: " to {target_language}, without outputting any other 
content, and without outputting anything related to "--Context: ", if provided.

CRITICAL: Preserve all numbering systems exactly as they appear in the source (1, 2, 3... or [1], [2]... or ①, ②... etc.).
DO NOT ADD numbering to headings or sections that are not numbered in the source text.

CRITICAL FOR REFERENCES: When translating Japanese reference entries like "14　松下安雄監修樋垣元良「福岡藩」", 
translate the COMPLETE reference including author names, titles, and formatting. Output should be 
"14. Author Name, 'Title'" NOT just the isolated number "14". Always translate the full reference text.

NUMBERING CONTINUATION - VERY IMPORTANT: 
- If the context shows "Previous numbering ended with: X. Reference", you MUST continue numbering from X+1 for any new numbered items on the current page.
- Do NOT restart numbering from 1 - always continue the sequence from the previous page.
- Example: If context shows "Previous numbering ended with: 25. Some Reference", and current page has more numbered items, they should be numbered 26, 27, 28, etc.
- This applies ONLY to numbered reference lists, NOT to section headings.

SECTION HEADINGS: If the source has section headings without numbers, translate them as headings without adding numbers.

IMPORTANT: Only add a "Footnotes:" section if there is actual explanatory footnote text at the bottom 
of the page. Do NOT add "Footnotes:" for simple citation numbers like (38), (39) within paragraphs.

Do not provide any prompts to the user, for example: "This is the translation of the current page.":

"""
    
    def translate_text(self, text: str, source_language: str, target_language: str, output_format: str = "console") -> str:
        """Translate text using the specified model with retry logic for content filters."""
        model = self._get_model()
        system_prompt, user_prompt_template = self._create_translation_prompt(source_language, target_language, output_format)
        user_prompt = user_prompt_template + text
        
        # Retry logic for content filter issues
        max_retries = MAX_RETRIES
        base_delay = BASE_RETRY_DELAY
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    # Exponential backoff with jitter
                    delay = base_delay * (2 ** attempt) + (0.1 * attempt)
                    logging.info(f'Retrying API call (attempt {attempt + 1}/{max_retries}) after {delay:.1f}s delay...')
                    time.sleep(delay)
                
                logging.info(f'Making API call to model: {model}')
                response = self.client.chat.completions.create( # type: ignore[misc]
                    model=model,
                    temperature=TRANSLATION_TEMPERATURE,
                    max_tokens=TRANSLATION_MAX_TOKENS,
                    top_p=TRANSLATION_TOP_P,
                    stream=False,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                )

                assert not isinstance(response, ABCIterator), "Unexpected stream response received."
                
                # Log response details
                if response.id:
                    logging.info(f'API call successful. Response ID: {response.id}')
                if response.model:
                    logging.info(f'Model used: {response.model}')
                
                # Log token usage if available
                if response.usage and response.usage.prompt_tokens is not None and response.usage.completion_tokens is not None and response.usage.total_tokens is not None:
                    # Record token usage
                    usage = self.token_tracker.record_usage(
                        model=response.model or model,
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        requested_model=model
                    )
                    
                    logging.info(f'Tokens used - Prompt: {response.usage.prompt_tokens}, '
                               f'Completion: {response.usage.completion_tokens}, '
                               f'Total: {response.usage.total_tokens}, '
                               f'Cost: ${usage.total_cost:.4f}')
                else:
                    logging.warning('No token usage information available in response.')
                
                if response.choices and len(response.choices) > 0 and response.choices[0].message:
                    content = response.choices[0].message.content
                    if content is not None and isinstance(content, str):
                        print("\n" + content)
                        logging.info('Translation completed successfully.')
                        return content
                else:
                    print("\n[No content returned by the model]")
                    logging.warning('No content returned by the model.')
                    return ""
                    
            except Exception as e:
                error_result = self._handle_translation_error(e)
                
                # If it's a content filter issue and we have retries left, try again
                if error_result == "content_filter_triggered" and attempt < max_retries - 1:
                    logging.warning(f'Content filter triggered on attempt {attempt + 1}, retrying...')
                    continue
                elif error_result == "content_filter_triggered":
                    logging.error(f'Content filter triggered after {max_retries} attempts, skipping this text')
                    return ""
                else:
                    # For other errors, return the result or re-raise
                    return error_result
        
        # This should never be reached, but just in case
        return ""
    
    def _handle_translation_error(self, error: Exception) -> str:
        """Handle translation errors and return appropriate response."""
        error_type = type(error).__name__
        error_message = str(error)
        
        # Check for specific PortKey error types
        if "context_length_exceeded" in error_message.lower() or "maximum context length" in error_message.lower():
            logging.error(f'Context length exceeded: {error_message}')
            return "context_length_exceeded"
        elif "rate_limit" in error_message.lower():
            logging.error(f'Rate limit exceeded: {error_message}')
            raise Exception(f'Rate limit exceeded: {error_message}')
        elif "invalid_request" in error_message.lower():
            logging.error(f'Invalid request: {error_message}')
            raise Exception(f'Invalid request: {error_message}')
        elif "authentication" in error_message.lower() or "unauthorized" in error_message.lower():
            logging.error(f'Authentication error: {error_message}')
            raise Exception(f'Authentication error: {error_message}')
        elif "content_filter" in error_message.lower() or "jailbreak" in error_message.lower():
            logging.error(f'Content filter triggered: {error_message}')
            return "content_filter_triggered"
        else:
            logging.error(f'API call failed with {error_type}: {error_message}')
            raise Exception(f'API call failed with {error_type}: {error_message}')
    
    def translate_page_text(self, abstract_text: str, page_text: str, previous_page: str, 
                          source_language: str, target_language: str, output_format: str = "console",
                          previous_translated: str = "") -> str:
        """Translate page text with context."""
        process_text = generate_process_text(abstract_text, page_text, previous_page, CONTEXT_PERCENTAGE, previous_translated)
        return self.translate_text(process_text, source_language, target_language, output_format)
    
    def generate_text(self, abstract_text: str, page_text: str, previous_page: str, 
                     page_num: int, source_language: str, target_language: str, output_format: str = "console", 
                     previous_translated: str = "") -> str:
        """Generate translated text for a page, handling context length limits."""
        result: list[str] = []
        parts_to_translate = [page_text]
        
        # Debug logging
        logging.info(f"Starting translation of page {page_num + 1}, original text length: {len(page_text)} chars")
        
        # Check for numbered citations in the original text
        import re
        citation_numbers = re.findall(r'（(\d+)）|[（\(](\d+)[）\)]', page_text)
        if citation_numbers:
            found_numbers = [num for group in citation_numbers for num in group if num]
            logging.info(f"Page {page_num + 1} contains citation numbers: {found_numbers}")

        while parts_to_translate:
            # Use pop(0) to ensure FIFO processing - translate parts in the correct order
            current_part = parts_to_translate.pop(0)
            logging.info(f"Translating part {len(result) + 1} of page {page_num + 1}, length: {len(current_part)} chars")
            
            translated_text = self.translate_page_text(
                abstract_text, current_part, previous_page, source_language, target_language, output_format, previous_translated
            )

            if translated_text == "context_length_exceeded":
                # Split the text in half and add to FRONT of queue to maintain order
                middle_index = len(current_part) // 2
                # Find a good split point (try to split at paragraph breaks or sentences)
                split_point = middle_index
                
                # Look for paragraph breaks near the middle
                for offset in range(100):  # Look within 100 chars of middle
                    if middle_index + offset < len(current_part) and current_part[middle_index + offset:middle_index + offset + 2] == '\n\n':
                        split_point = middle_index + offset + 2
                        break
                    elif middle_index - offset > 0 and current_part[middle_index - offset:middle_index - offset + 2] == '\n\n':
                        split_point = middle_index - offset + 2
                        break
                
                # If no paragraph break found, look for sentence endings
                if split_point == middle_index:
                    for offset in range(50):  # Look within 50 chars for sentence endings
                        if middle_index + offset < len(current_part) and current_part[middle_index + offset] in '.!?。':
                            split_point = middle_index + offset + 1
                            break
                        elif middle_index - offset > 0 and current_part[middle_index - offset] in '.!?。':
                            split_point = middle_index - offset + 1
                            break
                
                first_half = current_part[:split_point].strip()
                second_half = current_part[split_point:].strip()
                
                # Insert at the beginning to maintain order
                if first_half:
                    parts_to_translate.insert(0, first_half)
                if second_half:
                    parts_to_translate.insert(1 if first_half else 0, second_half)
                    
                logging.warning(f"Context length exceeded on page {page_num + 1}, split into {len([p for p in [first_half, second_half] if p])} parts")
                
            elif translated_text == "content_filter_triggered":
                result.append(f"\n***Content filter triggered on page {page_num + 1} - text skipped***\n")
                logging.error(f"Content filter triggered on page {page_num + 1}")
            elif translated_text == '':
                result.append(f"\n***Translation error on page {page_num + 1}.***\n")
                logging.error(f"Translation returned empty result on page {page_num + 1}")
            else:
                result.append(translated_text)
                logging.info(f"Successfully translated part {len(result)} of page {page_num + 1}, output length: {len(translated_text)} chars")
                
                # Check if numbered citations were preserved in translation
                translated_numbers = re.findall(r'[（\(](\d+)[）\)]', translated_text)
                if translated_numbers:
                    logging.info(f"Part {len(result)} of page {page_num + 1} contains translated numbers: {translated_numbers}")

        final_result = f"\n\n-- Page {page_num + 1} -- \n\n" + "\n".join(result)
        logging.info(f"Completed translation of page {page_num + 1}, final length: {len(final_result)} chars")
        return final_result

    def translate_document(self, pages: Iterable[PDFPage], abstract_text: Optional[str], page_nums_str: Optional[str],
                           source_language: str, target_language: str, output_file: Optional[str] = None, 
                           auto_save: bool = False, progressive_save: bool = False, input_file_path: Optional[str] = None) -> List[str]:
        """Translate all pages in a document."""
        from ..output.file_output import FileOutputHandler
        
        document_text: list[str] = []
        start_page, end_page = extract_page_nums(page_nums_str)
        
        # Determine output format based on whether file output is requested
        if output_file:
            if output_file.lower().endswith('.pdf'):
                output_format = "pdf"
            elif output_file.lower().endswith('.txt'):
                output_format = "txt"
            else:
                output_format = "file"
        elif auto_save:
            output_format = "txt"  # Auto-save defaults to txt format
        else:
            output_format = "console"
        
        # Apply page range if specified
        if page_nums_str:
            pages = islice(pages, start_page, end_page + 1)

        # For progressive saving
        progressive_output_path = None

        page_text = ""
        previous_translated = ""
        for i, page in tqdm(enumerate(pages, start=start_page), desc="Translating... ", ascii=True):
            previous_page = page_text
            page_text = self.pdf_processor.process_page(page)
            
            try:
                translated_text = self.generate_text(
                    abstract_text or '', page_text, previous_page, i, source_language, target_language, output_format, previous_translated
                )
                document_text.append(translated_text)
                
                # Update translated context for next page
                previous_translated = translated_text
                
                # Add delay between pages to prevent rate limiting and content filter triggers
                # This helps avoid jailbreak detection issues
                if i > start_page:  # Don't delay on the first page
                    time.sleep(PAGE_DELAY_SECONDS)
                
                # Save page progressively if requested
                if progressive_save and (output_file or auto_save):
                    is_first_page = (i == start_page)
                    progressive_output_path = FileOutputHandler.save_page_progressively(
                        translated_text, 
                        input_file_path,
                        output_file,
                        auto_save,
                        source_language,
                        target_language,
                        is_first_page
                    )
                    
            except Exception as e:
                error_message = f"\n***Translation error on page {i + 1}: {e}***\n"
                document_text.append(error_message)
                print(f"Error on page {i + 1}: {e}")
                
                # Still save the error message progressively
                if progressive_save and (output_file or auto_save):
                    is_first_page = (i == start_page and len(document_text) == 1)
                    FileOutputHandler.save_page_progressively(
                        error_message,
                        input_file_path,
                        output_file,
                        auto_save,
                        source_language,
                        target_language,
                        is_first_page
                    )
                
                # Continue with next page instead of stopping
                continue

        # If progressive saving was used, inform user about the output file
        if progressive_save and progressive_output_path:
            print(f"\nProgressive translation saved to: {progressive_output_path}")

        return document_text
    
    def translate_text_pages(self, text_pages: List[str], abstract_text: Optional[str],
                            source_language: str, target_language: str, output_file: Optional[str] = None, 
                            auto_save: bool = False, progressive_save: bool = False, input_file_path: Optional[str] = None) -> List[str]:
        """Translate pre-extracted text pages (e.g., from Word documents)."""
        from ..output.file_output import FileOutputHandler
        
        document_text: list[str] = []
        
        # Determine output format based on whether file output is requested
        if output_file:
            if output_file.lower().endswith('.pdf'):
                output_format = "pdf"
            elif output_file.lower().endswith('.docx'):
                output_format = "docx"
            elif output_file.lower().endswith('.txt'):
                output_format = "txt"
            else:
                output_format = "file"
        elif auto_save:
            output_format = "txt"  # Auto-save defaults to txt format
        else:
            output_format = "console"

        # For progressive saving
        progressive_output_path = None

        previous_page = ""
        previous_translated = ""
        for i, page_text in tqdm(enumerate(text_pages), desc="Translating... ", ascii=True):
            try:
                translated_text = self.generate_text(
                    abstract_text or '', page_text, previous_page, i, source_language, target_language, output_format, previous_translated
                )
                document_text.append(translated_text)
                
                # Update previous page and translated text for context
                previous_page = page_text
                previous_translated = translated_text
                
                # Add delay between API calls (except for first page)
                if i > 0:  # Don't delay on the first page
                    time.sleep(PAGE_DELAY_SECONDS)
                
                # Save page progressively if requested
                if progressive_save and (output_file or auto_save):
                    is_first_page = (i == 0)
                    progressive_output_path = FileOutputHandler.save_page_progressively(
                        translated_text, 
                        input_file_path,
                        output_file,
                        auto_save,
                        source_language,
                        target_language,
                        is_first_page
                    )
                    
            except Exception as e:
                error_message = f"\n***Translation error on section {i + 1}: {e}***\n"
                document_text.append(error_message)
                print(f"Error on section {i + 1}: {e}")
                
                # Save page progressively if requested (even with error)
                if progressive_save and (output_file or auto_save):
                    is_first_page = (i == 0)
                    progressive_output_path = FileOutputHandler.save_page_progressively(
                        error_message, 
                        input_file_path,
                        output_file,
                        auto_save,
                        source_language,
                        target_language,
                        is_first_page
                    )

        # If progressive saving was used, print the final output path
        if progressive_save and progressive_output_path:
            print(f"\nProgressive saving completed. Final output: {progressive_output_path}")

        return document_text
