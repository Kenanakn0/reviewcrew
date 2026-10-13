import pytest

from reviewcrew.webhook.events import PullRequestEvent, skip_reason
from tests.helpers import pull_request_payload


@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened", "ready_for_review"])
def test_reviewed_actions_are_processed(action: str) -> None:
    event = PullRequestEvent.model_validate(pull_request_payload(action=action))

    assert skip_reason(event) is None


@pytest.mark.parametrize("action", ["closed", "edited", "labeled", "assigned"])
def test_other_actions_are_skipped(action: str) -> None:
    event = PullRequestEvent.model_validate(pull_request_payload(action=action))

    assert skip_reason(event) == f"action '{action}' is not reviewed"


def test_draft_pull_requests_are_skipped() -> None:
    event = PullRequestEvent.model_validate(pull_request_payload(draft=True))

    assert skip_reason(event) == "pull request is a draft"


def test_payload_fields_are_parsed() -> None:
    event = PullRequestEvent.model_validate(pull_request_payload(number=12, installation_id=99))

    assert event.pull_request.number == 12
    assert event.pull_request.head.sha == "abc123"
    assert event.repository.full_name == "octo/demo"
    assert event.installation.id == 99
