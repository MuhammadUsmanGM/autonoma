"""Shared utilities for channel adapters."""

from __future__ import annotations


def split_message(text: str, max_len: int = 2000) -> list[str]:
    """Split a long message into chunks, breaking at newlines or spaces."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to break at last newline before limit
        idx = text.rfind("\n", 0, max_len)
        if idx == -1:
            # Try space
            idx = text.rfind(" ", 0, max_len)
        if idx == -1:
            # Hard cut
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip()
    return chunks
