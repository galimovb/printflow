"""model_reference: source_redraw with ready model photos instead of people drawn from the prompt.

The print audience picks the models: women for a female print, men for a male one, and a unisex print
gets two frames with a man and two with a woman. Every frame takes a different model of the library.
"""

from .redraw import MODEL_FRAMES, RedrawPipeline

UNISEX_FRAMES = ("male", "male", "female", "female")


class ModelReferencePipeline(RedrawPipeline):
    def person(self, index: int, audience: str):
        if index >= MODEL_FRAMES:
            return None
        gender = audience if audience in ("female", "male") else UNISEX_FRAMES[index]
        return self.cards.models.pick(gender, self.job.design_number or 0, index)
