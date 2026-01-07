"""
Confidence Scoring Module
=========================
Asymmetric confidence thresholds and Kelly sizing for OVER/UNDER bets.
"""

from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass
from enum import Enum
import math

class BetType(str, Enum):
    OVER = "over"
    UNDER = "under"
    MONEYLINE = "moneyline"
    SPREAD = "spread"

class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SKIP = "skip"

@dataclass
class ConfidenceResult:
    """Result of confidence scoring."""
    bet_type: str
    edge: float  # Points of edge
    confidence_level: str
    kelly_fraction: float  # Recommended Kelly multiplier
    suggested_stake_pct: float  # % of bankroll
    parlay_recommendation: str
    should_bet: bool
    reason: str

# Asymmetric thresholds
THRESHOLDS = {
    "under": {
        "high": 1.5,    # 1.5+ point edge = high confidence
        "medium": 0.75,
        "low": 0.25,
        "kelly_mult": 1.0  # Full Kelly for unders
    },
    "over": {
        "high": 3.0,    # 3.0+ point edge = high confidence (higher bar!)
        "medium": 2.0,
        "low": 1.0,
        "kelly_mult": 0.25  # Quarter Kelly for overs
    },
    "moneyline": {
        "high": 8.0,    # 8%+ probability edge
        "medium": 5.0,
        "low": 2.0,
        "kelly_mult": 0.5
    },
    "spread": {
        "high": 2.0,    # 2+ point edge
        "medium": 1.0,
        "low": 0.5,
        "kelly_mult": 0.5
    }
}

# Parlay recommendations
PARLAY_RULES = {
    ("under", "high"): "4-5 leg parlay OK",
    ("under", "medium"): "2-3 leg parlay",
    ("under", "low"): "Straight bet only",
    ("over", "high"): "Straight bet only (no parlays for overs)",
    ("over", "medium"): "SKIP - not enough edge",
    ("over", "low"): "SKIP",
    ("moneyline", "high"): "2-3 leg parlay OK",
    ("moneyline", "medium"): "Straight bet only",
    ("spread", "high"): "2-3 leg parlay OK",
    ("spread", "medium"): "Straight bet only",
}


def calculate_confidence(
    bet_type: str,
    model_prediction: float,
    market_line: float,
    model_probability: Optional[float] = None,
    std_deviation: float = 10.0  # Default std dev for totals
) -> ConfidenceResult:
    """
    Calculate confidence level with asymmetric thresholds.
    
    Args:
        bet_type: over, under, moneyline, or spread
        model_prediction: Model's predicted value (e.g., 215.5 for total)
        market_line: Current market line (e.g., 220.5)
        model_probability: For moneyline, the win probability
        std_deviation: Standard deviation for normalizing edge
    
    Returns:
        ConfidenceResult with recommendation
    """
    bet_type = bet_type.lower()
    thresholds = THRESHOLDS.get(bet_type, THRESHOLDS["spread"])
    
    # Calculate edge
    if bet_type == "moneyline" and model_probability is not None:
        # For moneyline, edge is probability difference
        implied_prob = 0.5  # Simplified - would calculate from odds
        edge = (model_probability - implied_prob) * 100  # As percentage points
    else:
        # For totals/spreads, edge is point difference
        edge = abs(model_prediction - market_line)
    
    # Determine confidence level
    if edge >= thresholds["high"]:
        confidence = ConfidenceLevel.HIGH
    elif edge >= thresholds["medium"]:
        confidence = ConfidenceLevel.MEDIUM
    elif edge >= thresholds["low"]:
        confidence = ConfidenceLevel.LOW
    else:
        confidence = ConfidenceLevel.SKIP
    
    # Kelly fraction (asymmetric)
    kelly_mult = thresholds["kelly_mult"]
    base_kelly = min(edge / 100, 0.25)  # Cap at 25% of bankroll
    kelly_fraction = base_kelly * kelly_mult
    
    # Suggested stake
    suggested_stake_pct = round(kelly_fraction * 100, 2)
    
    # Parlay recommendation
    parlay_key = (bet_type, confidence.value)
    parlay_rec = PARLAY_RULES.get(parlay_key, "Straight bet only")
    
    # Should bet?
    should_bet = confidence in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM]
    
    # Special rule: Skip marginal OVERs
    if bet_type == "over" and confidence == ConfidenceLevel.MEDIUM:
        should_bet = False
        parlay_rec = "SKIP - OVERs require HIGH confidence"
    
    # Reason
    if should_bet:
        reason = f"{edge:.1f} point edge exceeds {bet_type.upper()} threshold"
    else:
        reason = f"Edge ({edge:.1f}) below {bet_type.upper()} threshold ({thresholds['medium']})"
    
    return ConfidenceResult(
        bet_type=bet_type,
        edge=round(edge, 2),
        confidence_level=confidence.value,
        kelly_fraction=round(kelly_fraction, 4),
        suggested_stake_pct=suggested_stake_pct,
        parlay_recommendation=parlay_rec,
        should_bet=should_bet,
        reason=reason
    )


def calculate_asymmetric_kelly(
    bet_type: str,
    win_probability: float,
    american_odds: int,
    bankroll: float = 1000.0
) -> Dict[str, Any]:
    """
    Calculate Kelly bet size with asymmetric multipliers.
    
    OVERs get quarter Kelly, UNDERs get full/half Kelly.
    """
    # Convert American odds to decimal
    if american_odds > 0:
        decimal_odds = (american_odds / 100) + 1
    else:
        decimal_odds = (100 / abs(american_odds)) + 1
    
    # Standard Kelly formula
    b = decimal_odds - 1
    q = 1 - win_probability
    p = win_probability
    
    kelly_fraction = (b * p - q) / b
    kelly_fraction = max(kelly_fraction, 0)  # No negative bets
    
    # Apply asymmetric multiplier
    bet_type = bet_type.lower()
    if bet_type == "over":
        multiplier = 0.25  # Quarter Kelly for overs
    elif bet_type == "under":
        multiplier = 0.75  # 3/4 Kelly for unders (conservative)
    else:
        multiplier = 0.5  # Half Kelly for others
    
    adjusted_fraction = kelly_fraction * multiplier
    adjusted_fraction = min(adjusted_fraction, 0.05)  # Cap at 5% of bankroll
    
    bet_amount = round(adjusted_fraction * bankroll, 2)
    
    return {
        "bet_type": bet_type,
        "win_probability": win_probability,
        "odds": american_odds,
        "raw_kelly_fraction": round(kelly_fraction, 4),
        "multiplier": multiplier,
        "adjusted_fraction": round(adjusted_fraction, 4),
        "recommended_bet": bet_amount,
        "bankroll": bankroll
    }


def get_parlay_suggestion(legs: list) -> Dict[str, Any]:
    """
    Suggest parlay strategy based on legs.
    
    Rules:
    - High confidence UNDERs: 4-5 leg parlays OK
    - Mixed: 2-3 leg max
    - Any OVERs: No parlays, straight bets only
    """
    under_high = sum(1 for l in legs if l.get("bet_type") == "under" and l.get("confidence") == "high")
    under_total = sum(1 for l in legs if l.get("bet_type") == "under")
    over_total = sum(1 for l in legs if l.get("bet_type") == "over")
    
    if over_total > 0:
        return {
            "recommendation": "NO_PARLAY",
            "reason": "OVERs should be straight bets only",
            "max_legs": 1,
            "suggested_action": "Remove OVERs from parlay or bet them separately"
        }
    
    if under_high >= 3:
        return {
            "recommendation": "AGGRESSIVE_PARLAY",
            "reason": f"{under_high} high-confidence UNDERs detected",
            "max_legs": 5,
            "suggested_action": "4-5 leg UNDER parlay is favorable"
        }
    
    if under_total >= 2:
        return {
            "recommendation": "CONSERVATIVE_PARLAY",
            "reason": "Mixed confidence UNDERs",
            "max_legs": 3,
            "suggested_action": "2-3 leg parlay recommended"
        }
    
    return {
        "recommendation": "STRAIGHT_BETS",
        "reason": "Not enough high-confidence picks",
        "max_legs": 1,
        "suggested_action": "Bet individually"
    }


# Performance tracking structure
class BetTypePerformance:
    """Track performance by bet type for auto-pausing."""
    
    def __init__(self):
        self.stats = {
            "over": {"bets": 0, "wins": 0, "roi": 0.0, "paused": False},
            "under": {"bets": 0, "wins": 0, "roi": 0.0, "paused": False},
            "moneyline": {"bets": 0, "wins": 0, "roi": 0.0, "paused": False},
            "spread": {"bets": 0, "wins": 0, "roi": 0.0, "paused": False}
        }
    
    def record_bet(self, bet_type: str, won: bool, profit: float, stake: float):
        bt = bet_type.lower()
        if bt in self.stats:
            self.stats[bt]["bets"] += 1
            if won:
                self.stats[bt]["wins"] += 1
            # Update ROI
            total_staked = self.stats[bt]["bets"] * stake  # Simplified
            self.stats[bt]["roi"] = (profit / total_staked * 100) if total_staked > 0 else 0
            
            # Auto-pause check
            if self.stats[bt]["bets"] >= 10:
                win_rate = self.stats[bt]["wins"] / self.stats[bt]["bets"]
                if win_rate < 0.48:
                    self.stats[bt]["paused"] = True
    
    def should_bet(self, bet_type: str) -> tuple:
        bt = bet_type.lower()
        if bt not in self.stats:
            return True, "Unknown bet type"
        
        if self.stats[bt]["paused"]:
            win_rate = self.stats[bt]["wins"] / max(self.stats[bt]["bets"], 1)
            return False, f"{bt.upper()} paused: {win_rate:.1%} win rate < 48%"
        
        return True, "OK"
    
    def get_summary(self) -> Dict[str, Any]:
        summary = {}
        for bt, data in self.stats.items():
            bets = data["bets"]
            wins = data["wins"]
            win_rate = (wins / bets * 100) if bets > 0 else 0
            summary[bt] = {
                "bets": bets,
                "wins": wins,
                "losses": bets - wins,
                "win_rate": round(win_rate, 1),
                "roi": round(data["roi"], 1),
                "status": "⚠️ PAUSED" if data["paused"] else "✅ Active"
            }
        return summary
