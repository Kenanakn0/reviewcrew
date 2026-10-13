"""List prices for cost estimates in the evaluation report.

USD per million tokens (input, output), Anthropic first-party API list prices as of
2026-10. Output includes thinking tokens, which the API bills as output. Update this table
when prices change; unknown models are reported without a cost.
"""

from reviewcrew.llm.base import TokenUsage

PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


def cost_usd(model: str, usage: TokenUsage) -> float | None:
    prices = PRICES_PER_MILLION.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    return (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1_000_000
