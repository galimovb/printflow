"""Prompt text for every paid request, grouped by algorithm.

Builders return plain strings; the generator only attaches images and calls the API.
"""

from .gallery import (
    RECOLOR_ACTIONS,
    extract_print_prompt,
    gallery_analysis_prompt,
    recolor_print_prompt,
    tone_print_prompt,
    verify_prints_prompt,
)
from .photo import PERSONS, SCENE_KEYS, live_photo_prompt, look, template_photo_prompt
from .standard import describe_prompt, outfit_flatlay_prompt, standard_extract_prompt, standard_model_prompt

__all__ = [
    "PERSONS",
    "RECOLOR_ACTIONS",
    "SCENE_KEYS",
    "describe_prompt",
    "extract_print_prompt",
    "gallery_analysis_prompt",
    "live_photo_prompt",
    "look",
    "outfit_flatlay_prompt",
    "recolor_print_prompt",
    "standard_extract_prompt",
    "standard_model_prompt",
    "template_photo_prompt",
    "tone_print_prompt",
    "verify_prints_prompt",
]
