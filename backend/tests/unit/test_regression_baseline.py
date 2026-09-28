from tests.evals.regression import check_regression, get_baseline_entry, load_baseline


def test_load_baseline_returns_a_list_of_entries():
    baseline = load_baseline()
    assert isinstance(baseline, list)
    assert len(baseline) > 0
    for entry in baseline:
        assert {"run_type", "model_used", "score", "prompt_version"} <= entry.keys()


def test_get_baseline_entry_finds_a_real_committed_entry():
    entry = get_baseline_entry("classification", "ollama/llama3.2:1b", metric=None)
    assert entry is not None
    assert entry["prompt_version"] == "v1"


def test_get_baseline_entry_distinguishes_by_metric():
    consistency = get_baseline_entry("faithfulness", "ollama/llama3.2:1b", metric="consistency_rate")
    accuracy = get_baseline_entry("faithfulness", "ollama/llama3.2:1b", metric="reliable_accuracy")
    assert consistency is not None
    assert accuracy is not None
    assert consistency["score"] != accuracy["score"]


def test_get_baseline_entry_returns_none_when_not_found():
    assert get_baseline_entry("classification", "some/unknown-model") is None


def test_check_regression_true_when_below_tolerance():
    assert check_regression(current_score=0.50, baseline_score=0.67, tolerance=0.1) is True


def test_check_regression_false_within_tolerance():
    # Real observed cross-architecture variance (ADR-0020, ADR-0022's
    # CI incident) was ~0.09 on a 12-example set — must not flag this.
    assert check_regression(current_score=0.58, baseline_score=0.67, tolerance=0.1) is False


def test_check_regression_false_when_score_improves():
    assert check_regression(current_score=0.90, baseline_score=0.67, tolerance=0.1) is False


def test_check_regression_false_just_inside_tolerance_boundary():
    # Deliberately not testing the exact float boundary (0.67 - 0.1 is
    # not exactly representable), just inside it either direction.
    assert check_regression(current_score=0.571, baseline_score=0.67, tolerance=0.1) is False


def test_check_regression_true_just_outside_tolerance_boundary():
    assert check_regression(current_score=0.569, baseline_score=0.67, tolerance=0.1) is True
