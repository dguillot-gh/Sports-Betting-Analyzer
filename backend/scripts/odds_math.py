"""
Odds Math Utilities
Converts between probabilities and American odds formats.
Used by the NASCAR AI Prediction Hub.
"""


def probability_to_american(prob: float) -> str:
    """Convert a probability (0-1) to American odds string.
    
    Examples:
        0.08  -> "+1150"
        0.55  -> "-122"
        0.25  -> "+300"
    """
    if prob <= 0 or prob >= 1:
        return "--"
    
    if prob >= 0.5:
        odds = -round(prob / (1 - prob) * 100)
        return str(odds)
    else:
        odds = round((1 - prob) / prob * 100)
        return f"+{odds}"


def american_to_probability(odds_str: str) -> float:
    """Convert American odds string to implied probability.
    
    Examples:
        "+500"  -> 0.1667
        "-150"  -> 0.6000
    """
    if not odds_str or odds_str in ("--", "N/A"):
        return 0.0
    
    try:
        odds = int(odds_str.replace("+", ""))
        if odds > 0:
            return 100.0 / (odds + 100.0)
        else:
            return abs(odds) / (abs(odds) + 100.0)
    except (ValueError, ZeroDivisionError):
        return 0.0


def calculate_value_edge(model_prob: float, market_odds_str: str) -> float:
    """Calculate the edge (%) between model probability and market implied probability.
    
    Positive = model thinks driver is undervalued by market (value bet).
    Negative = model thinks driver is overvalued.
    """
    market_prob = american_to_probability(market_odds_str)
    if market_prob <= 0:
        return 0.0
    return (model_prob - market_prob) / market_prob


def classify_value(edge: float) -> str:
    """Classify a value edge into a human-readable rating."""
    if edge > 0.15:
        return "strong_value"
    elif edge > 0.05:
        return "value"
    elif edge > -0.05:
        return "fair"
    else:
        return "overpriced"
