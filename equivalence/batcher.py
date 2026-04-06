from collections import defaultdict

from .db import Product


def create_batches(products: list[Product], batch_size: int = 15) -> list[list[Product]]:
    """Split products into LLM-friendly batches.

    Strategy: group by brand, then interleave shops so cross-shop products
    from the same brand land in the same batch.
    """
    by_brand: dict[str, dict[str, list[Product]]] = defaultdict(lambda: defaultdict(list))
    for p in products:
        brand_key = (p.brand or "").strip().lower()
        by_brand[brand_key][p.shop_type].append(p)

    # Interleave: for each brand, round-robin across shops
    ordered: list[Product] = []
    for brand_key in sorted(by_brand.keys()):
        shops = by_brand[brand_key]
        shop_lists = list(shops.values())
        max_len = max(len(sl) for sl in shop_lists)
        for i in range(max_len):
            for sl in shop_lists:
                if i < len(sl):
                    ordered.append(sl[i])

    # Chunk into batches
    return [ordered[i : i + batch_size] for i in range(0, len(ordered), batch_size)]


def filter_batches_with_ids(
    batches: list[list[Product]], target_ids: set[int]
) -> list[list[Product]]:
    """Keep only batches that contain at least one product from target_ids."""
    return [b for b in batches if any(p.id in target_ids for p in b)]
