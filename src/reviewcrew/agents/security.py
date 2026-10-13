"""Security reviewer: injection, secrets, auth, XSS, unsafe deserialization and more."""

from typing import ClassVar

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentName


class SecurityAgent(BaseAgent):
    name: ClassVar[AgentName] = "security"
    role: ClassVar[str] = "a senior application security engineer"
    focus: ClassVar[str] = "security vulnerabilities"
