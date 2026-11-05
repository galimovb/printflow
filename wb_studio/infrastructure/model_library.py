"""Ready model photos for model_reference: <dir>/female/*.jpg and <dir>/male/*.jpg."""

import random
from dataclasses import dataclass
from pathlib import Path

from printflow.domain.errors import PermanentError
from printflow.wb_studio.paths import ASSETS

DEFAULT_DIR = ASSETS / "models"


@dataclass(frozen=True)
class ModelPhoto:
    gender: str
    photo: bytes


class ModelLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)

    @classmethod
    def from_env(cls, env) -> "ModelLibrary":
        return cls(env.get("PRINTFLOW_WB_MODELS_DIR") or DEFAULT_DIR)

    def photos(self, gender: str) -> list[Path]:
        return sorted(p for p in (self.root / gender).glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))

    def pick(self, gender: str, seed: int, frame: int) -> ModelPhoto:
        """The vendor number shuffles the models, so every frame of a card shows a different person."""
        photos = self.photos(gender)
        if not photos:
            raise PermanentError(f"Нет готовых моделей: {self.root / gender}")
        order = random.Random(seed).sample(photos, len(photos))
        return ModelPhoto(gender, order[frame % len(order)].read_bytes())
