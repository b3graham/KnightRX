"""PR tracking: estimated-1RM math, auto-detection, and the tested/estimated/historical
separation that keeps pre-rhabdo numbers out of programming."""
from app import prs, rules


def test_estimate_1rm_formulas():
    assert round(prs.estimate_1rm(100, 5), 1) == 116.7        # Epley
    assert round(prs.estimate_1rm(100, 5, "brzycki"), 1) == 112.5
    assert prs.estimate_1rm(185, 1) == 185.0                   # 1 rep = the weight
    assert prs.estimate_1rm(0, 5) == 0.0                       # guard


def test_high_rep_estimate_is_clamped():
    # A 30-rep set must not yield a wilder estimate than the 12-rep clamp allows.
    assert prs.estimate_1rm(100, 30) == prs.estimate_1rm(100, 12)


def test_detect_estimated_1rm_from_set_only_improves():
    bs = rules.movement_by_id("back_squat")
    first = prs.detect_from_set(bs, 135, 5)
    assert first and first[0]["source"] == "estimated" and first[0]["value"] == 157.5
    prs.record_prs("back_squat", first)
    # A lighter set is not a PR.
    assert prs.detect_from_set(bs, 115, 5) == []
    # A heavier effort is.
    better = prs.detect_from_set(bs, 155, 5)
    assert better and better[0]["value"] > 157.5


def test_logged_set_never_becomes_a_tested_max():
    bs = rules.movement_by_id("back_squat")
    prs.record_prs("back_squat", prs.detect_from_set(bs, 135, 5))
    # Nothing tested should exist from a mere working set.
    assert prs.best_value("back_squat", ("1RM",), sources=("tested",)) is None
    assert prs.best_value("back_squat", ("1RM",), sources=("estimated",)) == 157.5


def test_max_reps_autodetect_is_tested_measurement():
    pu = rules.movement_by_id("strict_pullup")
    out = prs.detect_from_set(pu, None, 8)
    assert out and out[0]["kind"] == "max_reps" and out[0]["source"] == "tested"
    assert out[0]["value"] == 8 and out[0]["unit"] == "reps"


def test_historical_is_reference_only_never_programmed():
    prs.log_historical("deadlift", "1RM", 405)
    assert prs.programming_max("deadlift") is None                     # engine sees nothing
    assert prs.best_value("deadlift", ("1RM",), exclude_historical=False) == 405  # still visible as reference
    # An estimate later should be used for programming, but never the 405.
    prs.record_prs("deadlift", [{"kind": "1RM", "value": 225.0, "unit": "lb", "source": "estimated"}])
    assert prs.programming_max("deadlift") == 225.0


def test_tested_max_preferred_over_estimate():
    prs.record_prs("press", [{"kind": "1RM", "value": 95.0, "unit": "lb", "source": "estimated"}])
    prs.log_tested_max("press", "1RM", 100)
    assert prs.programming_max("press") == 100.0
