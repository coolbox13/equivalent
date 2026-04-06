# CLAUDE.md

@.wolf/OPENWOLF.md

## Overview

Product equivalence pipeline for the Omfietser project. Identifies equivalent products across Dutch supermarket chains (AH, JUMBO, PLUS, ALDI, KRUIDVAT, SPAR) using hierarchical grouping + local LLM (Apfel/Apple Foundation Model).

## Project Structure

```
equivalence/           # Core pipeline package
  config.py            # DB + Apfel config from .env
  db.py                # PostgreSQL queries and writes
  batcher.py           # Smart batch construction (brand-sorted, cross-shop interleaved)
  llm.py               # Apfel API client + prompt
  parser.py            # Parse LLM pair output, validate, filter
run_equivalence.py     # CLI entry point
.env                   # DB credentials (replica at 192.168.178.100)
schema.sql             # product_essences table schema (reference)
docs/                  # PRD and index strategy docs
archive/               # Old experimental code (semantic_matcher, HuggingFace tests, etc.)
```

## How It Works

1. **Group** active products by `main_category` + `normalized_quantity_unit` (81 groups)
2. **Batch** each group into 10-product batches, sorted by brand with cross-shop interleaving
3. **Send** batches to Apfel (localhost:11435) which identifies matching pairs
4. **Parse** LLM output (format: `ID1=ID2 (identical|similar|alternative)`)
5. **Write** validated cross-shop pairs to `product_equivalence` table

## Running

```bash
pip install -r requirements.txt

# Stats overview
python run_equivalence.py --mode stats

# Process all groups (~17 hours, free)
python run_equivalence.py --mode full

# Process only groups with new/unmatched products
python run_equivalence.py --mode incremental

# Process single group
python run_equivalence.py --group "Frisdrank, sappen, siropen, water|l"

# Dry run (no DB writes)
python run_equivalence.py --group "Drogisterij|stuk" --dry-run

# Remove equivalences for deactivated products
python run_equivalence.py --mode cleanup
```

## Prerequisites

- **Apfel server** running: `apfel --serve --port 11435`
- **PostgreSQL** replica accessible at 192.168.178.100 (credentials in .env)
- Python packages: psycopg2-binary, aiohttp, python-dotenv

## Database

- **Source**: `products` table (56,918 active products, 7 shops)
- **Target**: `product_equivalence` table (source_product_id, target_product_id, equivalence_type, similarity_score)
- Equivalence types: `identical`, `similar`, `alternative`
- UNIQUE constraint on (source_product_id, target_product_id)
- Canonical ordering enforced: source_id < target_id

## Performance

- ~10-20 seconds per batch of 10 products
- ~5,700 batches for full dataset = ~17 hours
- Incremental updates: minutes (only processes groups with new products)
- Cost: €0 (local Apple Foundation Model)
