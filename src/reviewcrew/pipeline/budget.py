"""Per-PR token budget shared by all agents."""

import asyncio

from reviewcrew.llm.base import TokenUsage

# Allowance for the model's output (and reasoning) when reserving budget for a call.
OUTPUT_ALLOWANCE_TOKENS = 4000


class TokenBudget:
    """Reserve before a call, settle after it.

    Agents run concurrently, so checking only the tokens already spent would let every
    in-flight call overshoot. Reserving an estimate first keeps the total (spent plus
    reserved) within the limit; the actual usage replaces the estimate when the call ends.

    Estimates are pessimistic, so a reservation that does not fit *now* may well fit once
    the calls in flight settle: it waits for them instead of giving up. A chunk is skipped
    only when nothing is in flight and it still does not fit.
    """

    def __init__(self, limit: int | None) -> None:
        self.limit = limit
        self.spent = 0
        self._reserved = 0
        self._changed = asyncio.Condition()

    def _fits(self, estimate: int) -> bool:
        return self.limit is None or self.spent + self._reserved + estimate <= self.limit

    async def reserve(self, estimate: int) -> bool:
        async with self._changed:
            while not self._fits(estimate):
                if self._reserved == 0:
                    return False
                await self._changed.wait()
            self._reserved += estimate
            return True

    async def settle(self, estimate: int, usage: TokenUsage) -> None:
        async with self._changed:
            self._reserved -= estimate
            self.spent += usage.total_tokens
            self._changed.notify_all()

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.spent >= self.limit
