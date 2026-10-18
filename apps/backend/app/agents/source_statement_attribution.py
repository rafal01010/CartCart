from __future__ import annotations

import re

from app.schemas.ids import ProductId
from app.schemas.products import CanonicalProduct


def named_product_ids(
    text: str, products: tuple[CanonicalProduct, ...]
) -> set[ProductId]:
    mentions = [
        (match.start(), match.end(), product.product_id)
        for product in products
        for identity in (product.model, product.name)
        if identity
        for match in re.finditer(
            r"(?<!\w)" + re.escape(identity) + r"(?!\w)", text, re.IGNORECASE
        )
    ]
    return {
        product_id
        for start, end, product_id in mentions
        if not any(
            other_start <= start
            and other_end >= end
            and other_end - other_start > end - start
            for other_start, other_end, other_id in mentions
            if other_id != product_id
        )
    }


def contextual_product_ids(
    quote: str,
    observed_texts: tuple[str, ...],
    products: tuple[CanonicalProduct, ...],
) -> set[ProductId]:
    named = named_product_ids(quote, products)
    if named:
        return named
    targets: set[ProductId] = set()
    for text in observed_texts:
        for occurrence in re.finditer(re.escape(quote), text):
            prefix = text[max(0, occurrence.start() - 600) : occurrence.start()]
            before = re.split(r"[.!?\n]", prefix)
            suffix = (
                ""
                if quote.rstrip().endswith((".", "!", "?"))
                else re.split(r"[.!?\n]", text[occurrence.end() :], maxsplit=1)[0]
            )
            sentence = before[-1] + quote + suffix
            local = named_product_ids(sentence, products)
            if not local and len(before) > 1:
                previous = next(
                    (part for part in reversed(before[:-1]) if part.strip()), ""
                )
                local = named_product_ids(previous, products)
            targets.update(local)
    return targets
