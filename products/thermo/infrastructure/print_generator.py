"""Принт термонаклейки через OpenAI Images на хромакее (services/printing/chromakey); промпты — domain/prompts."""
from __future__ import annotations

from typing import Any

from printflow.config import OpenAISettings
from printflow.products.thermo.domain.prompts import (
    NAME_PROMPT, hires_prompt, preview_prompt, reference_prompt, subject_prompt, theme_prompt,
)
from printflow.services.printing.chromakey import ChromakeyPrintGenerator


class ThermoPrintGenerator(ChromakeyPrintGenerator):
    def __init__(self, settings: OpenAISettings, generation: dict[str, Any]) -> None:
        super().__init__(settings, generation, NAME_PROMPT)

    def subject_prompt(self, theme: dict[str, Any], drawn: list[str]) -> str:
        return subject_prompt(theme, drawn)

    def subject_image_prompt(self, theme: dict[str, Any], subject: str) -> str:
        return theme_prompt(theme, subject, self.area)

    def preview_prompt(self, theme: str) -> str:
        return preview_prompt(theme, self.area)

    def reference_prompt(self, note: str) -> str:
        return reference_prompt(note, self.area)

    def hires_prompt(self) -> str:
        return hires_prompt(self.area)
