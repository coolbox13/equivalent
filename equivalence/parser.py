import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

TYPE_MAP = {
    "identical": "identical",
    "identiek": "identical",
    "similar": "similar",
    "vergelijkbaar": "similar",
    "alternative": "alternative",
    "alternatief": "alternative",
}

SCORE_MAP = {
    "identical": 0.95,
    "similar": 0.75,
    "alternative": 0.55,
}

# Pattern: ID=ID (type) — with optional brackets, spaces, etc.
PAIR_PATTERN = re.compile(
    r"\[?(\d+)\]?\s*=\s*\[?(\d+)\]?\s*\((\w+)\)"
)


@dataclass
class EquivalencePair:
    source_product_id: int
    target_product_id: int
    equivalence_type: str
    similarity_score: float

    def as_tuple(self) -> tuple:
        return (self.source_product_id, self.target_product_id, self.equivalence_type, self.similarity_score)


def parse_pairs(
    response_text: str,
    valid_ids: set[int],
    product_shops: dict[int, str],
) -> list[EquivalencePair]:
    """Parse line-based pair output from LLM into validated equivalence pairs."""
    pairs: list[EquivalencePair] = []
    seen: set[tuple[int, int]] = set()

    for line in response_text.splitlines():
        line = line.strip()
        if not line:
            continue

        m = PAIR_PATTERN.search(line)
        if not m:
            continue

        try:
            id_a = int(m.group(1))
            id_b = int(m.group(2))
        except ValueError:
            continue

        raw_type = m.group(3).strip().lower()
        eq_type = TYPE_MAP.get(raw_type)
        if eq_type is None:
            log.debug("Unknown type '%s' in line: %s", raw_type, line)
            continue

        # Validate IDs exist in input
        if id_a not in valid_ids:
            log.debug("ID %d not in input batch", id_a)
            continue
        if id_b not in valid_ids:
            log.debug("ID %d not in input batch", id_b)
            continue

        # Skip same-shop pairs
        if product_shops.get(id_a) == product_shops.get(id_b):
            log.debug("Same-shop pair (%d, %d), skipping", id_a, id_b)
            continue

        # Canonical ordering
        lo, hi = min(id_a, id_b), max(id_a, id_b)
        if (lo, hi) in seen:
            continue
        seen.add((lo, hi))

        score = SCORE_MAP.get(eq_type, 0.5)
        pairs.append(EquivalencePair(
            source_product_id=lo,
            target_product_id=hi,
            equivalence_type=eq_type,
            similarity_score=score,
        ))

    return pairs
