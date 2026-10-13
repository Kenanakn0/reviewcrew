"""Performance reviewer: N+1 queries, unbounded work, complexity, blocking I/O."""

from typing import ClassVar

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentName


class PerformanceAgent(BaseAgent):
    name: ClassVar[AgentName] = "performance"
    role: ClassVar[str] = "a senior performance engineer"
    focus: ClassVar[str] = "performance and scalability problems"
