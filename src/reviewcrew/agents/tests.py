"""Test reviewer: changed logic without tests and untested edge cases."""

from typing import ClassVar

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentName


class TestAgent(BaseAgent):
    __test__ = False  # not a pytest test class despite the name

    name: ClassVar[AgentName] = "tests"
    role: ClassVar[str] = "a senior engineer who specialises in testing"
    focus: ClassVar[str] = "missing or ineffective tests for the changed logic"
