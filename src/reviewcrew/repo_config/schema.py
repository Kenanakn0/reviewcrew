"""Schema and parser for the optional `.reviewcrew.yml` at the repository root.

Example:

    agents: [security, tests]       # which reviewers run (default: all)
    min_severity: medium            # hide findings below this (default: low)
    ignore:                         # extra paths to skip, see globs.py
      - "docs/**"
      - "*.snap"
    max_comments: 10                # inline comments per PR (default: server setting)
    language: tr                    # review language: en | tr
"""

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import ErrorDetails

from reviewcrew.agents.models import AgentName, Severity

CONFIG_PATH = ".reviewcrew.yml"
MAX_CONFIG_BYTES = 64 * 1024
MAX_COMMENTS_LIMIT = 50


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agents: tuple[AgentName, ...] | None = Field(default=None, min_length=1)
    min_severity: Severity = "low"
    ignore: tuple[str, ...] = Field(default=(), max_length=100)
    max_comments: int | None = Field(default=None, ge=0, le=MAX_COMMENTS_LIMIT)
    language: Literal["en", "tr"] | None = None

    @field_validator("agents")
    @classmethod
    def _unique_agents(cls, value: tuple[AgentName, ...] | None) -> tuple[AgentName, ...] | None:
        return tuple(dict.fromkeys(value)) if value is not None else None

    @field_validator("ignore")
    @classmethod
    def _non_empty_patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not pattern.strip() for pattern in value):
            raise ValueError("ignore patterns must not be empty")
        return value


class LoadedConfig(BaseModel):
    """The effective config plus where it came from and what was wrong with it."""

    model_config = ConfigDict(frozen=True)

    config: RepoConfig = RepoConfig()
    source: Literal["defaults", "file"] = "defaults"
    errors: tuple[str, ...] = ()


def _format_error(error: ErrorDetails) -> str:
    location = ".".join(str(part) for part in error["loc"]) or "(root)"
    return f"`{location}`: {error['msg']}"


def parse_config(text: str | None) -> LoadedConfig:
    """Parse the file's text. Invalid files fall back to defaults and report why.

    Error messages carry the field and the problem but never echo the offending value.
    """
    if text is None:
        return LoadedConfig()
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        return LoadedConfig(errors=(f"file is larger than {MAX_CONFIG_BYTES // 1024} KB",))
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        return LoadedConfig(errors=(f"invalid YAML{where}",))
    if data is None:  # empty file
        return LoadedConfig(source="file")
    if not isinstance(data, dict):
        return LoadedConfig(errors=("the top level must be a mapping of settings",))
    try:
        return LoadedConfig(config=RepoConfig.model_validate(data), source="file")
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        return LoadedConfig(errors=tuple(_format_error(e) for e in errors))
