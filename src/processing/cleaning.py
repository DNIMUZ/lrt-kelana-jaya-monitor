from __future__ import annotations


def normalize_text(text: str) -> str:
    """Normalize whitespace while preserving the original text in storage."""
    return " ".join(text.split())
