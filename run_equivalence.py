#!/usr/bin/env python3
"""Omfietser Product Equivalence Pipeline.

Usage:
    python run_equivalence.py --mode full          # Process all groups
    python run_equivalence.py --mode incremental   # Only groups with new products
    python run_equivalence.py --mode cleanup       # Remove stale equivalences
    python run_equivalence.py --mode stats         # Print statistics
    python run_equivalence.py --group "Drogisterij|stuk"  # Single group
    python run_equivalence.py --dry-run            # Don't write to DB
"""

import argparse
import asyncio
import logging
import sys
import time

import aiohttp

from equivalence.config import DBConfig, ApfelConfig
from equivalence import db
from equivalence.batcher import create_batches, filter_batches_with_ids
from equivalence.llm import cluster_batch
from equivalence.parser import parse_pairs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("equivalence_run.log"),
    ],
)
log = logging.getLogger(__name__)


def print_stats(db_cfg: DBConfig):
    groups = db.get_all_groups(db_cfg)
    total_products = sum(g.count for g in groups)
    stats = db.get_equivalence_stats(db_cfg)

    log.info("=== Product Equivalence Stats ===")
    log.info("Active products: %d across %d groups", total_products, len(groups))
    log.info("Equivalences: %d total", stats["total"])
    for eq_type, info in stats["by_type"].items():
        log.info("  %s: %d (avg score %.3f)", eq_type, info["count"], info["avg_score"])

    log.info("")
    log.info("Top 10 groups:")
    for g in groups[:10]:
        log.info("  %-45s | %-6s | %5d products | %d shops", g.category, g.unit, g.count, g.shop_count)


async def process_group(
    db_cfg: DBConfig,
    apfel_cfg: ApfelConfig,
    category: str,
    unit: str,
    dry_run: bool = False,
    unmatched_ids: set[int] | None = None,
) -> int:
    """Process a single category+unit group. Returns total pairs written."""
    products = db.get_products_by_group(db_cfg, category, unit)
    if len(products) < 2:
        log.info("  Skipping: only %d product(s)", len(products))
        return 0

    # Need at least 2 shops for cross-shop matching
    shops = {p.shop_type for p in products}
    if len(shops) < 2:
        log.info("  Skipping: only %d shop(s)", len(shops))
        return 0

    batches = create_batches(products, apfel_cfg.batch_size)

    # In incremental mode, only process batches with new products
    if unmatched_ids is not None:
        batches = filter_batches_with_ids(batches, unmatched_ids)
        if not batches:
            log.info("  No batches with new products, skipping")
            return 0

    log.info("  %d products, %d batches to process", len(products), len(batches))

    total_pairs = 0
    valid_id_set = {p.id for p in products}
    product_shops = {p.id: p.shop_type for p in products}

    async with aiohttp.ClientSession() as session:
        for i, batch in enumerate(batches):
            batch_start = time.time()
            response = await cluster_batch(session, batch, category, unit, apfel_cfg)

            if response is None:
                log.warning("  Batch %d/%d: no response, skipping", i + 1, len(batches))
                continue

            pairs = parse_pairs(response, valid_id_set, product_shops)
            elapsed = time.time() - batch_start

            if pairs and not dry_run:
                written = db.write_equivalences(db_cfg, [p.as_tuple() for p in pairs])
                total_pairs += written
                log.info(
                    "  Batch %d/%d: %d pairs (%d written) in %.1fs",
                    i + 1, len(batches), len(pairs), written, elapsed,
                )
            elif pairs:
                total_pairs += len(pairs)
                log.info(
                    "  Batch %d/%d: %d pairs (dry-run) in %.1fs",
                    i + 1, len(batches), len(pairs), elapsed,
                )
            else:
                log.info(
                    "  Batch %d/%d: no matches in %.1fs",
                    i + 1, len(batches), elapsed,
                )

            # Pause between calls
            if i < len(batches) - 1:
                await asyncio.sleep(apfel_cfg.pause_between_calls)

    return total_pairs


async def run_full(db_cfg: DBConfig, apfel_cfg: ApfelConfig, dry_run: bool):
    groups = db.get_all_groups(db_cfg)
    log.info("Full run: %d groups to process", len(groups))

    grand_total = 0
    for idx, g in enumerate(groups):
        log.info("[%d/%d] %s | %s (%d products, %d shops)",
                 idx + 1, len(groups), g.category, g.unit, g.count, g.shop_count)
        pairs = await process_group(db_cfg, apfel_cfg, g.category, g.unit, dry_run)
        grand_total += pairs

    log.info("=== Full run complete: %d total pairs ===", grand_total)


async def run_incremental(db_cfg: DBConfig, apfel_cfg: ApfelConfig, dry_run: bool):
    # Step 1: cleanup stale equivalences
    removed = db.cleanup_inactive(db_cfg)
    if removed:
        log.info("Cleaned up %d stale equivalences", removed)

    # Step 2: find unmatched products
    unmatched = db.get_unmatched_product_ids(db_cfg)
    log.info("Found %d unmatched products", len(unmatched))
    if not unmatched:
        log.info("Nothing to process")
        return

    # Step 3: determine affected groups
    groups = db.get_groups_with_unmatched(db_cfg, unmatched)
    log.info("Processing %d groups with new products", len(groups))

    grand_total = 0
    for idx, g in enumerate(groups):
        log.info("[%d/%d] %s | %s (%d new products)",
                 idx + 1, len(groups), g.category, g.unit, g.count)
        pairs = await process_group(db_cfg, apfel_cfg, g.category, g.unit, dry_run, unmatched)
        grand_total += pairs

    log.info("=== Incremental run complete: %d total pairs ===", grand_total)


async def run_single_group(db_cfg: DBConfig, apfel_cfg: ApfelConfig, group_str: str, dry_run: bool):
    parts = group_str.split("|")
    if len(parts) != 2:
        log.error("Group must be 'category|unit', got: %s", group_str)
        return
    category, unit = parts[0].strip(), parts[1].strip()
    log.info("Single group: %s | %s", category, unit)
    pairs = await process_group(db_cfg, apfel_cfg, category, unit, dry_run)
    log.info("=== Group complete: %d pairs ===", pairs)


def main():
    parser = argparse.ArgumentParser(description="Omfietser Product Equivalence Pipeline")
    parser.add_argument("--mode", choices=["full", "incremental", "cleanup", "stats"], default="stats")
    parser.add_argument("--group", type=str, help='Single group: "Category|unit"')
    parser.add_argument("--dry-run", action="store_true", help="Parse LLM output but don't write to DB")
    args = parser.parse_args()

    db_cfg = DBConfig()
    apfel_cfg = ApfelConfig()

    if args.group:
        asyncio.run(run_single_group(db_cfg, apfel_cfg, args.group, args.dry_run))
    elif args.mode == "stats":
        print_stats(db_cfg)
    elif args.mode == "cleanup":
        removed = db.cleanup_inactive(db_cfg)
        log.info("Cleaned up %d stale equivalences", removed)
    elif args.mode == "full":
        asyncio.run(run_full(db_cfg, apfel_cfg, args.dry_run))
    elif args.mode == "incremental":
        asyncio.run(run_incremental(db_cfg, apfel_cfg, args.dry_run))


if __name__ == "__main__":
    main()
