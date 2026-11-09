"""Unit tests for src.confidence_scoring (pure logic, no I/O)."""
from confidence_scoring import (
    BetTypePerformance,
    calculate_asymmetric_kelly,
    calculate_confidence,
    get_parlay_suggestion,
)


# ---------------------------------------------------------------------------
# calculate_confidence
# ---------------------------------------------------------------------------

class TestCalculateConfidenceTotals:
    def test_over_high_confidence(self):
        # 215.5 model vs 220.5 market -> 5.0 edge >= over 'high' (3.0)
        r = calculate_confidence("over", model_prediction=215.5, market_line=220.5)
        assert r.confidence_level == "high"
        assert r.should_bet is True
        assert r.parlay_recommendation.startswith("Straight bet only")  # overs never in parlays

    def test_over_medium_is_skipped_by_special_rule(self):
        # Edge 2.0 == over 'medium' threshold, but OVER+MEDIUM => no bet
        r = calculate_confidence("over", model_prediction=218.5, market_line=220.5)
        assert r.confidence_level == "medium"
        assert r.should_bet is False

    def test_over_low_is_not_bet(self):
        r = calculate_confidence("over", model_prediction=219.5, market_line=220.5)
        assert r.confidence_level in ("low", "medium")
        assert r.should_bet is False

    def test_under_lower_bar_than_over(self):
        # Same 2.0 edge: over=medium(skip), under=high(bet)
        over = calculate_confidence("over", model_prediction=218.5, market_line=220.5)
        under = calculate_confidence("under", model_prediction=222.5, market_line=220.5)
        assert under.confidence_level == "high"
        assert under.should_bet is True
        assert over.should_bet is False

    def test_skip_when_edge_below_low_threshold(self):
        r = calculate_confidence("under", model_prediction=220.7, market_line=220.5)
        assert r.confidence_level == "skip"
        assert r.should_bet is False

    def test_kelly_mult_differs_by_direction(self):
        # 5-edge: over uses 0.25 mult, under uses 1.0 mult
        over = calculate_confidence("over", model_prediction=215.5, market_line=220.5)
        under = calculate_confidence("under", model_prediction=225.5, market_line=220.5)
        assert over.kelly_fraction * 4 == under.kelly_fraction


class TestCalculateConfidenceMoneyline:
    def test_moneyline_edge_from_probability(self):
        # Edge = (0.60 - 0.50) * 100 = 10 >= moneyline 'high' (8.0)
        r = calculate_confidence("moneyline", model_prediction=0.6, market_line=-150,
                                 model_probability=0.60)
        assert r.confidence_level == "high"
        assert r.should_bet is True

    def test_moneyline_skip_below_thresholds(self):
        # Edge = (0.51 - 0.50) * 100 = 1 < moneyline 'low' (2.0) => skip
        r = calculate_confidence("moneyline", model_prediction=0.51, market_line=-105,
                                 model_probability=0.51)
        assert r.confidence_level == "skip"
        assert r.should_bet is False

    def test_moneyline_low_is_not_bet(self):
        # Edge 2.0 == low threshold -> low confidence, no bet
        r = calculate_confidence("moneyline", model_prediction=0.52, market_line=-105,
                                 model_probability=0.52)
        assert r.confidence_level == "low"
        assert r.should_bet is False


class TestConfidenceResultShape:
    def test_fields_present_and_sane(self):
        r = calculate_confidence("under", model_prediction=225.5, market_line=220.5)
        assert r.bet_type == "under"
        assert abs(r.edge - 5.0) < 1e-9
        assert 0 <= r.kelly_fraction <= 0.25
        assert r.reason  # non-empty
        assert isinstance(r.should_bet, bool)


# ---------------------------------------------------------------------------
# calculate_asymmetric_kelly
# ---------------------------------------------------------------------------

class TestAsymmetricKelly:
    def test_no_bet_when_no_edge(self):
        # p=0.5, -100 odds -> b=1, kelly=(0.5-0.5)/1=0 -> no bet
        r = calculate_asymmetric_kelly("under", 0.5, -100)
        assert r["recommended_bet"] == 0.0

    def test_positive_kelly_when_edge_exists(self):
        r = calculate_asymmetric_kelly("under", 0.55, -110)
        # b = 100/110 = 0.909; kelly = (b*p - q)/b = (0.4999*0.55... ) > 0
        assert r["raw_kelly_fraction"] > 0
        assert r["recommended_bet"] > 0

    def test_over_gets_quarter_kelly(self):
        over = calculate_asymmetric_kelly("over", 0.60, -110)
        under = calculate_asymmetric_kelly("under", 0.60, -110)
        assert over["multiplier"] == 0.25
        assert under["multiplier"] == 0.75
        assert over["adjusted_fraction"] < under["adjusted_fraction"]

    def test_fraction_capped_at_5_percent(self):
        # Very long odds + high prob -> raw kelly large, must be capped
        r = calculate_asymmetric_kelly("under", 0.99, +1000, bankroll=10000)
        assert r["adjusted_fraction"] <= 0.05
        assert r["recommended_bet"] <= 500.0

    def test_known_value(self):
        # american +100 -> b=1; p=0.55 -> raw kelly = 0.55-0.45=0.10; under mult 0.75 => 0.075 -> capped 0.05
        r = calculate_asymmetric_kelly("under", 0.55, +100, bankroll=1000)
        assert r["raw_kelly_fraction"] == 0.1
        assert r["adjusted_fraction"] == 0.05
        assert r["recommended_bet"] == 50.0


# ---------------------------------------------------------------------------
# get_parlay_suggestion
# ---------------------------------------------------------------------------

class TestParlaySuggestion:
    def test_overs_block_parlays(self):
        legs = [{"bet_type": "over", "confidence": "high"}] * 5
        r = get_parlay_suggestion(legs)
        assert r["recommendation"] == "NO_PARLAY"
        assert r["max_legs"] == 1

    def test_three_high_unders_aggressive(self):
        legs = [{"bet_type": "under", "confidence": "high"}] * 3
        r = get_parlay_suggestion(legs)
        assert r["recommendation"] == "AGGRESSIVE_PARLAY"
        assert r["max_legs"] == 5

    def test_two_mixed_unders_conservative(self):
        legs = [{"bet_type": "under", "confidence": "medium"}] * 2
        r = get_parlay_suggestion(legs)
        assert r["recommendation"] == "CONSERVATIVE_PARLAY"
        assert r["max_legs"] == 3

    def test_single_leg_straight(self):
        r = get_parlay_suggestion([{"bet_type": "under", "confidence": "high"}])
        assert r["recommendation"] == "STRAIGHT_BETS"
        assert r["max_legs"] == 1

    def test_empty_legs(self):
        r = get_parlay_suggestion([])
        assert r["recommendation"] == "STRAIGHT_BETS"


# ---------------------------------------------------------------------------
# BetTypePerformance
# ---------------------------------------------------------------------------

class TestBetTypePerformance:
    def test_record_and_summary(self):
        perf = BetTypePerformance()
        perf.record_bet("under", True, 100.0, 200.0)
        summary = perf.get_summary()
        assert summary["under"]["bets"] == 1
        assert summary["under"]["wins"] == 1
        assert summary["under"]["losses"] == 0
        assert summary["under"]["win_rate"] == 100.0
        ok, _ = perf.should_bet("under")
        assert ok is True

    def test_auto_pause_after_10_bets_below_48_pct(self):
        perf = BetTypePerformance()
        # 3 wins, 7 losses in 10 bets (all $100 stakes)
        for i in range(10):
            perf.record_bet("over", i < 3, 90.0 if i < 3 else -100.0, 100.0)
        assert perf.stats["over"]["paused"] is True
        ok, reason = perf.should_bet("over")
        assert ok is False
        assert "paused" in reason

    def test_no_pause_when_win_rate_ok(self):
        perf = BetTypePerformance()
        for i in range(12):
            perf.record_bet("moneyline", i < 6, 100.0, 100.0)  # 50% win rate
        assert perf.stats["moneyline"]["paused"] is False

    def test_unknown_bet_type_allowed(self):
        perf = BetTypePerformance()
        ok, _ = perf.should_bet("prop")
        assert ok is True
