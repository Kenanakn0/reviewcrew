"""Notification recipients."""


def unique_emails(users: list, blocked: list[str]) -> list[str]:
    seen: list[str] = []
    for user in users:
        email = user.email.lower()
        if email not in seen and email not in blocked:
            seen.append(email)
    return seen
