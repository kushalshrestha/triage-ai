from app.rate_limit import check_rate_limit, reset_rate_limits


def setup_function():
    reset_rate_limits()


def test_allows_requests_under_the_limit():
    for _ in range(3):
        allowed, _ = check_rate_limit("k", max_requests=3, window_seconds=60, now=0.0)
        assert allowed is True


def test_blocks_the_request_that_exceeds_the_limit():
    for _ in range(3):
        check_rate_limit("k", max_requests=3, window_seconds=60, now=0.0)
    allowed, retry_after = check_rate_limit("k", max_requests=3, window_seconds=60, now=0.0)
    assert allowed is False
    assert retry_after > 0


def test_window_reset_allows_requests_again():
    for _ in range(3):
        check_rate_limit("k", max_requests=3, window_seconds=60, now=0.0)
    blocked, _ = check_rate_limit("k", max_requests=3, window_seconds=60, now=10.0)
    assert blocked is False

    allowed, _ = check_rate_limit("k", max_requests=3, window_seconds=60, now=61.0)
    assert allowed is True


def test_independent_keys_do_not_interfere():
    for _ in range(3):
        check_rate_limit("user-a", max_requests=3, window_seconds=60, now=0.0)
    allowed, _ = check_rate_limit("user-b", max_requests=3, window_seconds=60, now=0.0)
    assert allowed is True


def test_retry_after_reflects_remaining_window_time():
    check_rate_limit("k", max_requests=1, window_seconds=60, now=0.0)
    _, retry_after = check_rate_limit("k", max_requests=1, window_seconds=60, now=45.0)
    assert retry_after == 15.0
