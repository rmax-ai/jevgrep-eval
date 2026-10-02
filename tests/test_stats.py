from jevgrep_eval.stats import clustered_bootstrap, exact_mcnemar, strata_counts


def test_bootstrap_hand_cases_and_caveat():
    result = clustered_bootstrap([0, 0], reps=10, seed=3)
    assert result.confidence_interval == (0.0, 0.0)
    assert result.caveat == "no discordant observations"
    clustered = clustered_bootstrap([{"differences": [1, 1]}, {"differences": [0, 0]}], reps=20, seed=1)
    assert clustered.estimate == 0.5


def test_mcnemar_and_strata_counts():
    assert exact_mcnemar([True, True], [True, True]).p_value == 1.0
    assert exact_mcnemar([True, False], [False, True]).p_value == 1.0
    assert strata_counts([{"stratum": "b", "left_success": True, "right_success": False}])[0].stratum == "b"
