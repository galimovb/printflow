"""Prompt text for every paid request, grouped by algorithm.

Builders return plain strings; the generator only attaches images and calls the API.
"""

from .gallery import (
    RECOLOR_ACTIONS,
    extract_print_prompt,
    gallery_analysis_prompt,
    recolor_need_prompt,
    recolor_print_prompt,
    tone_print_prompt,
    verify_prints_prompt,
)
from .photo import PERSONS, SCENE_KEYS, live_photo_prompt, look
from .standard import describe_prompt, outfit_flatlay_prompt, standard_extract_prompt, standard_model_prompt
from .template import frame_check_prompt, frame_collage_prompt, frame_plan_prompt

__all__ = [
    "PERSONS",
    "RECOLOR_ACTIONS",
    "SCENE_KEYS",
    "describe_prompt",
    "extract_print_prompt",
    "frame_plan_prompt",
    "gallery_analysis_prompt",
    "live_photo_prompt",
    "look",
    "outfit_flatlay_prompt",
    "recolor_need_prompt",
    "recolor_print_prompt",
    "standard_extract_prompt",
    "standard_model_prompt",
    "frame_check_prompt",
    "frame_collage_prompt",
    "tone_print_prompt",
    "verify_prints_prompt",
]
