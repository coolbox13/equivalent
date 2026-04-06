import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import NamedTuple

import psycopg2
import psycopg2.extras

from .config import DBConfig

log = logging.getLogger(__name__)


class Product(NamedTuple):
    id: int
    shop_type: str
    title: str
    brand: str
    normalized_quantity_amount: float
    normalized_quantity_unit: str
    current_price: float


@dataclass
class GroupInfo:
    category: str
    unit: str
    count: int
    shop_count: int


@contextmanager
def connect(cfg: DBConfig):
    conn = psycopg2.connect(cfg.dsn)
    try:
        yield conn
    finally:
        conn.close()


def get_all_groups(cfg: DBConfig) -> list[GroupInfo]:
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT main_category, normalized_quantity_unit,
                       count(*) AS cnt, count(DISTINCT shop_type) AS shops
                FROM products
                WHERE is_active = true
                  AND main_category IS NOT NULL
                  AND normalized_quantity_unit IS NOT NULL
                GROUP BY main_category, normalized_quantity_unit
                ORDER BY cnt DESC
            """)
            return [
                GroupInfo(category=r[0], unit=r[1], count=r[2], shop_count=r[3])
                for r in cur.fetchall()
            ]


def get_products_by_group(cfg: DBConfig, category: str, unit: str) -> list[Product]:
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, shop_type, title, COALESCE(brand, ''),
                       COALESCE(normalized_quantity_amount, 0),
                       COALESCE(normalized_quantity_unit, ''),
                       COALESCE(current_price, 0)
                FROM products
                WHERE is_active = true
                  AND main_category = %s
                  AND normalized_quantity_unit = %s
                ORDER BY brand, title
            """, (category, unit))
            return [Product(*r) for r in cur.fetchall()]


def get_unmatched_product_ids(cfg: DBConfig) -> set[int]:
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id
                FROM products p
                WHERE p.is_active = true
                  AND p.main_category IS NOT NULL
                  AND p.normalized_quantity_unit IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM product_equivalence pe
                      WHERE pe.source_product_id = p.id OR pe.target_product_id = p.id
                  )
            """)
            return {r[0] for r in cur.fetchall()}


def get_groups_with_unmatched(cfg: DBConfig, unmatched_ids: set[int]) -> list[GroupInfo]:
    if not unmatched_ids:
        return []
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT main_category, normalized_quantity_unit,
                       count(*) AS cnt, count(DISTINCT shop_type) AS shops
                FROM products
                WHERE is_active = true
                  AND main_category IS NOT NULL
                  AND normalized_quantity_unit IS NOT NULL
                  AND id = ANY(%s)
                GROUP BY main_category, normalized_quantity_unit
                ORDER BY cnt DESC
            """, (list(unmatched_ids),))
            return [
                GroupInfo(category=r[0], unit=r[1], count=r[2], shop_count=r[3])
                for r in cur.fetchall()
            ]


def write_equivalences(cfg: DBConfig, pairs: list[tuple]) -> int:
    """Write equivalence pairs to DB. Each pair: (source_id, target_id, type, score).
    Returns number of rows inserted/updated."""
    if not pairs:
        return 0

    canonical = []
    for src, tgt, eq_type, score in pairs:
        lo, hi = min(src, tgt), max(src, tgt)
        canonical.append((lo, hi, eq_type, score))

    with connect(cfg) as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO product_equivalence
                    (source_product_id, target_product_id, equivalence_type, similarity_score)
                VALUES %s
                ON CONFLICT (source_product_id, target_product_id)
                DO UPDATE SET
                    equivalence_type = EXCLUDED.equivalence_type,
                    similarity_score = EXCLUDED.similarity_score,
                    updated_at = NOW()
                WHERE EXCLUDED.similarity_score > product_equivalence.similarity_score
                """,
                canonical,
                template="(%s, %s, %s, %s)",
            )
            count = cur.rowcount
        conn.commit()
    return count


def cleanup_inactive(cfg: DBConfig) -> int:
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM product_equivalence pe
                WHERE NOT EXISTS (
                    SELECT 1 FROM products p
                    WHERE p.id = pe.source_product_id AND p.is_active = true
                )
                OR NOT EXISTS (
                    SELECT 1 FROM products p
                    WHERE p.id = pe.target_product_id AND p.is_active = true
                )
            """)
            count = cur.rowcount
        conn.commit()
    return count


def get_equivalence_stats(cfg: DBConfig) -> dict:
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM product_equivalence")
            total = cur.fetchone()[0]
            cur.execute("""
                SELECT equivalence_type, count(*), round(avg(similarity_score), 3)
                FROM product_equivalence
                GROUP BY equivalence_type
                ORDER BY equivalence_type
            """)
            by_type = {r[0]: {"count": r[1], "avg_score": float(r[2])} for r in cur.fetchall()}
    return {"total": total, "by_type": by_type}
