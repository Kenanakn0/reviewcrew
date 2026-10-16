"""Outgoing notifications."""

MAX_ATTEMPTS = 3


class Notifier:
    def __init__(self, client):
        self.client = client

    def notify(self, user, message):
        if not user.email_verified:
            return False
        for attempt in range(MAX_ATTEMPTS):
            try:
                self.client.send(user.email, message)
                return True
            except ConnectionError:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
        return False
