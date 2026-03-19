"""
Script validation service.
Handles sensitive word detection and input validation.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Default blocklist path
_BLOCKLIST_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sensitive_words.txt"
_cached_words: set[str] | None = None


def _load_blocklist(path: Path | None = None) -> set[str]:
    """Load sensitive words from file. Cached after first load."""
    global _cached_words
    if _cached_words is not None:
        return _cached_words

    filepath = path or _BLOCKLIST_PATH
    words = set()
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    words.add(line)
    logger.info("Loaded %d sensitive words from %s", len(words), filepath)
    _cached_words = words
    return words


def reload_blocklist(path: Path | None = None) -> int:
    """Force reload the blocklist. Returns count of loaded words."""
    global _cached_words
    _cached_words = None
    words = _load_blocklist(path)
    return len(words)


def check_sensitive_words(text: str) -> list[dict]:
    """
    Check text for sensitive words.

    Returns list of hits: [{"keyword": str, "positions": [int, ...], "context": str}, ...]
    """
    if not text:
        return []

    words = _load_blocklist()
    hits = []

    for word in words:
        # Find all occurrences
        positions = []
        start = 0
        while True:
            idx = text.find(word, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + 1

        if positions:
            # Get context: 10 chars before and after first occurrence
            first_pos = positions[0]
            ctx_start = max(0, first_pos - 10)
            ctx_end = min(len(text), first_pos + len(word) + 10)
            context = text[ctx_start:ctx_end]

            hits.append({
                "keyword": word,
                "count": len(positions),
                "positions": positions,
                "context": f"...{context}..." if ctx_start > 0 else f"{context}...",
            })

    return hits


def validate_script_input(text: str, max_chars: int = 50000) -> dict:
    """
    Validate script text input.
    Returns: {"valid": bool, "char_count": int, "errors": [...]}
    """
    errors = []
    char_count = len(text) if text else 0

    if not text or not text.strip():
        errors.append("Script text cannot be empty")
    elif char_count > max_chars:
        errors.append(f"Script text exceeds maximum {max_chars} characters (got {char_count})")

    return {
        "valid": len(errors) == 0,
        "char_count": char_count,
        "errors": errors,
    }
