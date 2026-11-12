"""Ready mockup photo series for template_mockup, one bucket per gender.

Layout (tee-mockup-template-women / -men): series_<N>/<black|white>/<frame>.png, six frames per color.
Most series name their frames 01_hero ... 06_alternative; a few seated ones use other names
for the same slots, so a slot lists every name it may carry.
"""

import random
from dataclasses import dataclass

from printflow.domain.errors import PermanentError

SLOT_NAMES = {
    1: ("01_hero",),
    2: ("02_three_quarter", "02_seated_side", "02_seated_turn"),
    3: ("03_candid", "03_relaxed_front", "03_seated_front"),
    4: ("04_back_turn",),
    5: ("05_detail", "05_fabric_detail"),
    6: ("06_alternative", "06_standing", "06_standing_candid"),
}
DEFAULT_BUCKETS = {"female": "tee-mockup-template-women", "male": "tee-mockup-template-men"}
DEFAULT_SERIES = 103
# Series whose 01_hero shows the back (checked by eye, all 206 series); their front-facing 06 takes its place.
BACK_HERO = {"female": {3, 16, 45, 46, 62, 79, 88, 90, 91}, "male": set()}
FRONT_HERO_SLOT = 6
# Photos deleted from the buckets (a third arm, found by eye in all 2472 photos on 2026-11-11): (series, slot), both
# colors. The frame plan never offers them and the single-series fallback skips their series.
REMOVED = {"female": {(72, 4), (49, 2), (99, 4)}, "male": set()}


@dataclass(frozen=True)
class TemplateSeries:
    gender: str
    number: int


@dataclass(frozen=True)
class TemplateShot:
    """One ready photo: a series (a person in a place) and a slot (a pose); both colors exist for it."""

    gender: str
    series: int
    slot: int


# Every slot type once, so candidates differ in pose and framing; the extra ones are front poses.
CANDIDATE_SLOTS = (1, 2, 3, 4, 5, 6)
EXTRA_SLOTS = (1, 3, 6)


class TemplateLibrary:
    def __init__(self, storage, buckets: dict, series: int = DEFAULT_SERIES):
        self.storage = storage
        self.buckets = buckets
        self.series = series

    @classmethod
    def from_env(cls, storage, env) -> "TemplateLibrary":
        buckets = {
            "female": env.get("PRINTFLOW_WB_TEMPLATES_FEMALE_BUCKET") or DEFAULT_BUCKETS["female"],
            "male": env.get("PRINTFLOW_WB_TEMPLATES_MALE_BUCKET") or DEFAULT_BUCKETS["male"],
        }
        return cls(storage, buckets, int(env.get("PRINTFLOW_WB_TEMPLATE_SERIES") or DEFAULT_SERIES))

    def pick(self, audience: str, seed: int | str) -> TemplateSeries:
        """The vendor number (with the source link) picks one series, so every card of a theme shows another person and place.

        A unisex print takes the women's or the men's set, also by the vendor number.
        """
        chooser = random.Random(seed)
        gender = audience if audience in self.buckets else chooser.choice(sorted(self.buckets))
        number = chooser.randrange(1, self.series + 1)
        removed = {series for series, _ in REMOVED.get(gender, ())}
        while number in removed:  # the fallback uses four slots of one series: take the next complete one
            number = number % self.series + 1
        return TemplateSeries(gender, number)

    def candidates(self, audience: str, seed: int | str, count: int = 8) -> list[TemplateShot]:
        """Random photos for the frame plan: each from another series (another person and place) and, while slot
        types last, another slot (another pose and framing). One gender per card; unisex picks it by the seed."""
        chooser = random.Random(f"frames:{seed}")
        gender = audience if audience in self.buckets else chooser.choice(sorted(self.buckets))
        series = chooser.sample(range(1, self.series + 1), min(count, self.series))
        slots = list(CANDIDATE_SLOTS)
        chooser.shuffle(slots)
        slots += [chooser.choice(EXTRA_SLOTS) for _ in range(max(0, len(series) - len(slots)))]
        removed = REMOVED.get(gender, set())
        shots = []
        for number, slot in zip(series, slots, strict=False):
            if (number, slot) in removed:  # a deleted photo: another front pose of the same series
                slot = next(s for s in EXTRA_SLOTS if (number, s) not in removed)
            shots.append(TemplateShot(gender, number, slot))
        return shots

    async def shot(self, shot: TemplateShot, color: str) -> bytes:
        """The photo itself, as it is: the frame plan has already seen whether it shows the back."""
        bucket = self.buckets[shot.gender]
        for name in SLOT_NAMES[shot.slot]:
            key = f"series_{shot.series}/{color}/{name}.png"
            if await self.storage.exists(bucket, key):
                return await self.storage.get(bucket, key)
        raise PermanentError(f"Нет шаблона {bucket}/series_{shot.series}/{color} для кадра {shot.slot}")

    async def photo(self, series: TemplateSeries, color: str, slot: int) -> bytes:
        if slot == 1 and series.number in BACK_HERO.get(series.gender, ()):
            slot = FRONT_HERO_SLOT  # the print goes on the front, so the hero must face the camera
        bucket = self.buckets[series.gender]
        for name in SLOT_NAMES[slot]:
            key = f"series_{series.number}/{color}/{name}.png"
            if await self.storage.exists(bucket, key):
                return await self.storage.get(bucket, key)
        raise PermanentError(f"Нет шаблона {bucket}/series_{series.number}/{color} для кадра {slot}")
