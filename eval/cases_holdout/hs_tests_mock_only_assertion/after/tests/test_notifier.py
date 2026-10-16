from unittest import mock

from app.notifier import Notifier


def test_notify_sends_email():
    client = mock.Mock()
    user = mock.Mock(email="a@example.com")

    Notifier(client).notify(user, "hi")

    client.send.assert_called()
