"""Match predicted findings to expected ones and compute precision / recall / F1."""

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict

from eval.cases import ExpectedFinding
from reviewcrew.agents.models import AgentName, Finding

AGENTS: tuple[AgentName, ...] = ("security", "performance", "tests")
# A prediction counts if it lands within this many lines of the expected range.
LINE_TOLERANCE = 2


class Counts(BaseModel):
    model_config = ConfigDict(frozen=True)

    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(tp=self.tp + other.tp, fp=self.fp + other.fp, fn=self.fn + other.fn)

    @property
    def precision(self) -> float | None:
        found = self.tp + self.fp
        return self.tp / found if found else None

    @property
    def recall(self) -> float | None:
        expected = self.tp + self.fn
        return self.tp / expected if expected else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None  # nothing found or nothing expected: undefined
        return 2 * p * r / (p + r) if p + r else 0.0


def _distance(finding: Finding, expected: ExpectedFinding) -> int | None:
    """Lines between the prediction and the expected range, or None if out of tolerance."""
    start, end = finding.line, finding.end_line or finding.line
    gap = max(expected.start - end, start - expected.end, 0)
    return gap if gap <= LINE_TOLERANCE else None


def score_case(
    predicted: Sequence[Finding],
    expected: Sequence[ExpectedFinding],
    scored: Iterable[AgentName] = AGENTS,
) -> dict[AgentName, Counts]:
    """Per-agent counts. A prediction is a true positive when it has the expected category,
    file and (approximately) line; each expected finding can be matched only once. A finding
    in the wrong category counts against the agent that made it. Agents outside `scored`
    are left out entirely."""
    counts: dict[AgentName, Counts] = {}
    for agent in scored:
        mine = [f for f in predicted if f.agent == agent]
        wanted = [e for e in expected if e.category == agent]
        unmatched = list(range(len(mine)))
        tp = 0
        for target in wanted:
            best: tuple[int, int] | None = None  # (distance, index into mine)
            for index in unmatched:
                if mine[index].path != target.path:
                    continue
                distance = _distance(mine[index], target)
                if distance is not None and (best is None or distance < best[0]):
                    best = (distance, index)
            if best is not None:
                unmatched.remove(best[1])
                tp += 1
        counts[agent] = Counts(tp=tp, fp=len(unmatched), fn=len(wanted) - tp)
    return counts


def total(per_agent: Iterable[dict[AgentName, Counts]]) -> dict[AgentName, Counts]:
    result = {agent: Counts() for agent in AGENTS}
    for counts in per_agent:
        for agent, value in counts.items():
            result[agent] = result[agent] + value
    return result
