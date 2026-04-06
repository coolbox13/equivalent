import asyncio
import logging

import aiohttp

from .config import ApfelConfig
from .db import Product

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You match grocery products across different stores. Compare products and find equivalent ones.

Rules:
- ONLY match products from DIFFERENT stores (AH vs JUMBO, PLUS vs ALDI, etc.)
- NEVER match products from the SAME store
- Be STRICT: only match if products are truly equivalent
- If no matches exist, output nothing

Types:
- identical: Same product at different store (same brand, same product, same size)
- similar: Same brand, different variant at different store
- alternative: Different brand, same product type at different store

Output format - one match per line:
ID1=ID2 (identical)
ID1=ID2 (similar)
ID1=ID2 (alternative)

Example:
[100] AH | Lay's Naturel 225g
[200] JUMBO | Lay's Naturel 225g
[300] PLUS | PLUS Naturel chips 250g

100=200 (identical)
100=300 (alternative)"""


def format_product_line(p: Product) -> str:
    amount = f"{p.normalized_quantity_amount}{p.normalized_quantity_unit}"
    return f"[{p.id}] {p.shop_type} | {p.brand} | {p.title} | {amount}"


def build_user_prompt(products: list[Product], category: str, unit: str) -> str:
    lines = [f'Products in "{category}" ({unit}). List matching pairs:']
    for p in products:
        lines.append(format_product_line(p))
    lines.append("")
    lines.append("Matching pairs (only cross-store matches):")
    return "\n".join(lines)


async def cluster_batch(
    session: aiohttp.ClientSession,
    products: list[Product],
    category: str,
    unit: str,
    config: ApfelConfig,
) -> str | None:
    """Send a batch to Apfel and return the raw response text."""
    url = f"{config.base_url}/v1/chat/completions"
    user_prompt = build_user_prompt(products, category, unit)

    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    for attempt in range(config.max_retries):
        try:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=config.request_timeout),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("Apfel HTTP %d (attempt %d): %s", resp.status, attempt + 1, body[:200])
                    await asyncio.sleep(2 ** attempt)
                    continue

                data = await resp.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
                finish = choice.get("finish_reason", "")
                if finish == "length":
                    log.warning("Response truncated (finish_reason=length), %d chars", len(content))
                log.info("LLM response (%d chars): %s", len(content), content[:300])
                return content

        except asyncio.TimeoutError:
            log.warning("Apfel timeout (attempt %d)", attempt + 1)
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            log.warning("Apfel error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(2 ** attempt)

    log.error("Apfel: all %d retries failed for batch of %d products", config.max_retries, len(products))
    return None
