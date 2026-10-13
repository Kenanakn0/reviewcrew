"""Agent lookup by name."""

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentName
from reviewcrew.agents.performance import PerformanceAgent
from reviewcrew.agents.security import SecurityAgent
from reviewcrew.agents.tests import TestAgent

AGENT_CLASSES: dict[AgentName, type[BaseAgent]] = {
    "security": SecurityAgent,
    "performance": PerformanceAgent,
    "tests": TestAgent,
}
