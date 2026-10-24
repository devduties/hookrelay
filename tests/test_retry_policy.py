from datetime import UTC, datetime, timedelta

from hookrelay.retry import RetryPolicy


def test_server_error_is_scheduled_for_retry_with_exponential_delay():
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    decision = RetryPolicy().decide(status_code=503, error=None, attempt_number=1, now=now)

    assert decision.status == "retrying"
    assert decision.next_attempt_at == now + timedelta(seconds=5)


def test_network_error_uses_the_attempt_based_backoff():
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    decision = RetryPolicy().decide(
        status_code=None,
        error="connection timed out",
        attempt_number=3,
        retryable_error=True,
        now=now,
    )

    assert decision.status == "retrying"
    assert decision.next_attempt_at == now + timedelta(seconds=20)


def test_client_error_is_terminal():
    decision = RetryPolicy().decide(status_code=400, error=None, attempt_number=1)

    assert decision.status == "failed"
    assert decision.next_attempt_at is None


def test_blocked_target_error_is_not_retried():
    decision = RetryPolicy().decide(
        status_code=None,
        error="target resolves to a private address",
        attempt_number=1,
    )

    assert decision.status == "failed"
    assert decision.next_attempt_at is None


def test_rate_limited_response_is_retried():
    decision = RetryPolicy().decide(status_code=429, error=None, attempt_number=1)

    assert decision.status == "retrying"


def test_fifth_failed_attempt_exhausts_the_retry_budget():
    decision = RetryPolicy().decide(status_code=503, error=None, attempt_number=5)

    assert decision.status == "failed"
    assert decision.next_attempt_at is None


def test_retry_delay_is_capped_at_five_minutes():
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    decision = RetryPolicy(max_attempts=10).decide(
        status_code=503,
        error=None,
        attempt_number=8,
        now=now,
    )

    assert decision.status == "retrying"
    assert decision.next_attempt_at == now + timedelta(minutes=5)


def test_successful_response_is_delivered():
    decision = RetryPolicy().decide(status_code=204, error=None, attempt_number=1)

    assert decision.status == "delivered"
    assert decision.next_attempt_at is None
