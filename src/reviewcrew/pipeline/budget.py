"""Per-PR token budget shared by all agents."""

from reviewcrew.llm.base import TokenUsage

# Allowance for the model's output (and reasoning) when reserving budget for a call.
OUTPUT_ALLOWANCE_TOKENS = 4000


class TokenBudget:
    """Reserve before a call, settle after it.

    Agents run concurrently, so checking only the tokens already spent would let every
    in-flight call overshoot. Reserving an estimate first keeps the total (spent plus
    reserved) within the limit; the actual usage replaces the estimate when the call ends.
    Single event loop, no awaits inside methods: no lock needed.
    """

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.spent = 0
        self._reserved = 0

    def try_reserve(self, estimate: int) -> bool:
        if self.limit is not None and self.spent + self._reserved + estimate > self.limit:
            return False
        self._reserved += estimate
        return True

    def settle(self, estimate: int, usage: TokenUsage) -> None:
        self._reserved -= estimate
        self.spent += usage.total_tokens

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.spent >= self.limit
