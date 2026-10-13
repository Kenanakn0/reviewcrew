"""Mail provider configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MailConfig:
    api_key: str
    sender: str


def load_mail_config() -> MailConfig:
    api_key = os.environ.get("MAIL_API_KEY")
    if not api_key:
        raise RuntimeError("MAIL_API_KEY is not set")
    return MailConfig(api_key=api_key, sender=os.environ.get("MAIL_SENDER", "noreply@example.com"))
