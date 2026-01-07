"""
Model Lab API Endpoints
=======================
Testing sandbox for confidence scoring and bet type analysis.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging

from src.confidence_scoring import (
    calculate_confidence,
    calculate_asymmetric_kelly,
    get_parlay_suggestion,
    BetTypePerformance
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lab", tags=["Model Lab"])

# In-memory performance tracker for testing
_performance_tracker = BetTypePerformance()


class ConfidenceRequest(BaseModel):
    bet_type: str  # over, under, moneyline, spread
    model_prediction: float
    market_line: float
    model_probability: Optional[float] = None


class KellyRequest(BaseModel):
    bet_type: str
    win_probability: float
    american_odds: int
    bankroll: float = 1000.0


class ParlayLeg(BaseModel):
    bet_type: str
    confidence: str  # high, medium, low


class ParlayRequest(BaseModel):
    legs: List[ParlayLeg]


class RecordBetRequest(BaseModel):
    bet_type: str
    won: bool
    profit: float
    stake: float


@router.post("/confidence")
async def analyze_confidence(request: ConfidenceRequest):
    """
    Analyze a bet's confidence level with asymmetric thresholds.
    
    - UNDERs: 1.5pt edge = high confidence
    - OVERs: 3.0pt edge = high confidence (higher bar)
    """
    try:
        result = calculate_confidence(
            bet_type=request.bet_type,
            model_prediction=request.model_prediction,
            market_line=request.market_line,
            model_probability=request.model_probability
        )
        return {
            "bet_type": result.bet_type,
            "edge": result.edge,
            "confidence_level": result.confidence_level,
            "kelly_fraction": result.kelly_fraction,
            "suggested_stake_pct": result.suggested_stake_pct,
            "parlay_recommendation": result.parlay_recommendation,
            "should_bet": result.should_bet,
            "reason": result.reason
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kelly")
async def calculate_kelly(request: KellyRequest):
    """
    Calculate asymmetric Kelly bet size.
    
    - OVERs: Quarter Kelly
    - UNDERs: 3/4 Kelly
    - Others: Half Kelly
    """
    try:
        return calculate_asymmetric_kelly(
            bet_type=request.bet_type,
            win_probability=request.win_probability,
            american_odds=request.american_odds,
            bankroll=request.bankroll
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/parlay-suggestion")
async def suggest_parlay(request: ParlayRequest):
    """
    Get parlay strategy recommendation based on legs.
    
    Rules:
    - High confidence UNDERs: 4-5 leg parlays OK
    - Mixed: 2-3 leg max  
    - Any OVERs: No parlays, straight bets only
    """
    try:
        legs = [{"bet_type": l.bet_type, "confidence": l.confidence} for l in request.legs]
        return get_parlay_suggestion(legs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/record-bet")
async def record_bet(request: RecordBetRequest):
    """Record a bet result for performance tracking."""
    try:
        _performance_tracker.record_bet(
            bet_type=request.bet_type,
            won=request.won,
            profit=request.profit,
            stake=request.stake
        )
        can_bet, reason = _performance_tracker.should_bet(request.bet_type)
        return {
            "recorded": True,
            "bet_type": request.bet_type,
            "can_continue_betting": can_bet,
            "status": reason
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
async def get_performance():
    """Get performance summary by bet type."""
    return _performance_tracker.get_summary()


@router.post("/reset-performance")
async def reset_performance():
    """Reset performance tracker (for testing)."""
    global _performance_tracker
    _performance_tracker = BetTypePerformance()
    return {"reset": True}


@router.get("/thresholds")
async def get_thresholds():
    """Get current confidence thresholds."""
    from src.confidence_scoring import THRESHOLDS, PARLAY_RULES
    return {
        "thresholds": THRESHOLDS,
        "parlay_rules": {str(k): v for k, v in PARLAY_RULES.items()}
    }


@router.post("/batch-analyze")
async def batch_analyze(predictions: List[ConfidenceRequest]):
    """Analyze multiple predictions at once."""
    results = []
    for pred in predictions:
        result = calculate_confidence(
            bet_type=pred.bet_type,
            model_prediction=pred.model_prediction,
            market_line=pred.market_line,
            model_probability=pred.model_probability
        )
        results.append({
            "bet_type": result.bet_type,
            "edge": result.edge,
            "confidence_level": result.confidence_level,
            "should_bet": result.should_bet,
            "parlay_recommendation": result.parlay_recommendation
        })
    
    # Summary
    bettable = [r for r in results if r["should_bet"]]
    
    return {
        "predictions": results,
        "summary": {
            "total": len(results),
            "bettable": len(bettable),
            "skip": len(results) - len(bettable),
            "under_high": sum(1 for r in results if r["bet_type"] == "under" and r["confidence_level"] == "high"),
            "over_high": sum(1 for r in results if r["bet_type"] == "over" and r["confidence_level"] == "high")
        }
    }
