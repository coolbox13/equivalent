#!/usr/bin/env python3
"""Recover equivalence pairs from logged LLM responses."""

import re
import logging
import sys

from equivalence.config import DBConfig
from equivalence import db
from equivalence.parser import EquivalencePair, PAIR_PATTERN, TYPE_MAP, SCORE_MAP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def parse_log_file(log_path: str) -> list[EquivalencePair]:
    """Extract LLM responses from log and parse into pairs."""
    pairs = []
    seen_responses = set()

    with open(log_path, 'r') as f:
        content = f.read()

    # Find all LLM response blocks: "LLM response (XXX chars): ..."
    pattern = r"LLM response \(\d+ chars\): ([^\n]+(?:\n(?!.*INFO)[^\n]+)*)"
    matches = re.finditer(pattern, content)

    for match in matches:
        response_text = match.group(1).strip()

        # Skip if we've seen this exact response before
        if response_text in seen_responses:
            continue
        seen_responses.add(response_text)

        # Parse lines from response
        for line in response_text.split('\n'):
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
                continue

            lo, hi = min(id_a, id_b), max(id_a, id_b)
            score = SCORE_MAP.get(eq_type, 0.5)
            pairs.append(EquivalencePair(
                source_product_id=lo,
                target_product_id=hi,
                equivalence_type=eq_type,
                similarity_score=score,
            ))

    return pairs


def main():
    log_path = "equivalence_run.log"
    log.info("Parsing log file: %s", log_path)

    pairs = parse_log_file(log_path)
    log.info("Extracted %d pairs from log", len(pairs))

    if not pairs:
        log.error("No pairs found in log file")
        return

    # Deduplicate by (source, target)
    seen = set()
    unique_pairs = []
    for p in pairs:
        key = (p.source_product_id, p.target_product_id)
        if key not in seen:
            seen.add(key)
            unique_pairs.append(p)

    log.info("Deduplicated to %d unique pairs", len(unique_pairs))

    db_cfg = DBConfig()

    # Get valid product IDs
    log.info("Validating product IDs...")
    valid_ids = set()
    with db.connect(db_cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM products WHERE is_active = true")
            valid_ids = {r[0] for r in cur.fetchall()}

    log.info("Found %d active products", len(valid_ids))

    # Filter pairs with valid IDs and different source/target
    valid_pairs = [
        p for p in unique_pairs
        if p.source_product_id in valid_ids
        and p.target_product_id in valid_ids
        and p.source_product_id != p.target_product_id
    ]
    log.info("Filtered to %d pairs with valid product IDs", len(valid_pairs))

    log.info("Writing %d pairs to database...", len(valid_pairs))

    written = db.write_equivalences(db_cfg, [p.as_tuple() for p in valid_pairs])
    log.info("SUCCESS: %d pairs written to database", written)


if __name__ == "__main__":
    main()
