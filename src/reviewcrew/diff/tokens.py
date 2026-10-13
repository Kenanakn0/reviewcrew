"""Provider-independent token estimate used for budgeting prompt sizes."""

# Deliberately conservative: source code averages roughly 3-4 characters per token, so
# assuming 3 overestimates and keeps chunks safely below the real model limits.
CHARS_PER_TOKEN = 3


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)  # ceiling division


def char_budget(max_tokens: int) -> int:
    """Largest text length whose estimate stays within `max_tokens`."""
    return max_tokens * CHARS_PER_TOKEN
