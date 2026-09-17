from __future__ import annotations

from collections.abc import Iterable

_LRT_TERMS = ("lrt", "rapid kl", "rapidkl", "kelana jaya", "lrt kj", "kuala kaya")


def is_lrt_related(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in _LRT_TERMS)


def filter_lrt_posts(posts: Iterable[str]) -> list[str]:
    return [post for post in posts if is_lrt_related(post)]
