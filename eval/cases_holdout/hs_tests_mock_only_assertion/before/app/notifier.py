"""Outgoing notifications."""


class Notifier:
    def __init__(self, client):
        self.client = client

    def notify(self, user, message):
        self.client.send(user.email, message)
