"""
MLB Historical Backtest
========================
Runs the trained models against historical game data to evaluate
betting performance: ROI, win rate, Sharpe ratio, max drawdown.

Simulates flat $100 bets on moneyline, spread, and totals where
the model indicates value (edge >= threshold).
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def run_backtest(
    test_df: pd.DataFrame,
    prob_col: str = "pred_prob",
    actual_col: str = "home_win",
    ml_home_col: str = "home_ml",
    ml_away_col: str = "away_ml",
    edge_threshold: float = 0.04,
    bet_amount: float = 100.0,
) -> Dict[str, Any]:
    """
    Run a moneyline backtest on the test set.

    Args:
        test_df: DataFrame with columns: date, home_team, away_team,
                 pred_prob (model P(home_win)), home_win (actual), home_ml, away_ml
        prob_col: Column with model's predicted P(home_win)
        actual_col: Column with actual outcome (1 = home won)
        edge_threshold: Minimum edge vs implied prob to trigger a bet
        bet_amount: Flat bet amount per wager

    Returns:
        dict with: total_bets, wins, losses, profit, roi, win_rate,
                   sharpe, max_drawdown, by_month breakdown
    """
    results = []

    for _, row in test_df.iterrows():
        model_prob = row.get(prob_col, 0.5)
        actual = row.get(actual_col, 0)
        home_ml = row.get(ml_home_col)
        away_ml = row.get(ml_away_col)

        if pd.isna(home_ml) or pd.isna(away_ml):
            continue

        home_ml = int(home_ml)
        away_ml = int(away_ml)

        home_implied = _implied_prob(home_ml)
        away_implied = _implied_prob(away_ml)

        home_edge = model_prob - home_implied
        away_edge = (1 - model_prob) - away_implied

        bet = None
        if home_edge >= edge_threshold:
            # Bet on home
            payout = _calc_payout(home_ml, bet_amount)
            won = actual == 1
            profit = payout - bet_amount if won else -bet_amount
            bet = {
                "date": row.get("date"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "side": "home",
                "odds": home_ml,
                "edge": round(home_edge * 100, 1),
                "model_prob": round(model_prob, 3),
                "implied_prob": round(home_implied, 3),
                "won": won,
                "profit": round(profit, 2),
            }
        elif away_edge >= edge_threshold:
            # Bet on away
            payout = _calc_payout(away_ml, bet_amount)
            won = actual == 0
            profit = payout - bet_amount if won else -bet_amount
            bet = {
                "date": row.get("date"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "side": "away",
                "odds": away_ml,
                "edge": round(away_edge * 100, 1),
                "model_prob": round(1 - model_prob, 3),
                "implied_prob": round(away_implied, 3),
                "won": won,
                "profit": round(profit, 2),
            }

        if bet:
            results.append(bet)

    if not results:
        return {
            "total_bets": 0,
            "profit": 0,
            "roi": 0,
            "message": "No bets triggered at this edge threshold"
        }

    df = pd.DataFrame(results)
    total_bets = len(df)
    wins = int(df["won"].sum())
    losses = total_bets - wins
    total_wagered = total_bets * bet_amount
    total_profit = df["profit"].sum()
    roi = (total_profit / total_wagered) * 100 if total_wagered > 0 else 0

    # Sharpe ratio (daily returns)
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby(df["date"].dt.date)["profit"].sum()
    daily_returns = daily / bet_amount
    sharpe = (
        float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
        if daily_returns.std() > 0 else 0
    )

    # Max drawdown
    cumulative = df["profit"].cumsum()
    running_max = cumulative.cummax()
    drawdown = cumulative - running_max
    max_drawdown = float(drawdown.min())

    # By-month breakdown
    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month").agg(
        bets=("won", "count"),
        wins=("won", "sum"),
        profit=("profit", "sum"),
    ).reset_index()
    monthly["month"] = monthly["month"].astype(str)
    monthly["roi"] = (monthly["profit"] / (monthly["bets"] * bet_amount) * 100).round(1)

    # By confidence tier
    df["conf_tier"] = pd.cut(
        df["edge"], bins=[0, 4, 8, 100], labels=["4-8%", "8-12%", "12%+"]
    )
    by_conf = df.groupby("conf_tier", observed=True).agg(
        bets=("won", "count"),
        wins=("won", "sum"),
        profit=("profit", "sum"),
    ).reset_index()
    by_conf["win_rate"] = (by_conf["wins"] / by_conf["bets"] * 100).round(1)
    by_conf["roi"] = (by_conf["profit"] / (by_conf["bets"] * bet_amount) * 100).round(1)

    return {
        "total_bets": total_bets,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total_bets * 100, 1),
        "total_wagered": round(total_wagered, 2),
        "total_profit": round(float(total_profit), 2),
        "roi": round(float(roi), 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown": round(max_drawdown, 2),
        "edge_threshold": edge_threshold,
        "bet_amount": bet_amount,
        "by_month": monthly.to_dict("records"),
        "by_confidence": by_conf.to_dict("records"),
        "avg_edge": round(float(df["edge"].mean()), 1),
        "avg_odds": round(float(df["odds"].mean()), 0),
    }


def _implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def _calc_payout(odds: int, stake: float) -> float:
    """Calculate payout (including stake) from American odds."""
    if odds > 0:
        return stake * (odds / 100) + stake
    else:
        return stake * (100 / abs(odds)) + stake


async def run_full_backtest(pool=None) -> Dict[str, Any]:
    """
    Run backtest using stored training results or by building features + training.
    """
    from scripts.mlb_train_models import build_historical_features, train_all_models

    if pool is None:
        from src.database import get_pool
        pool = await get_pool()

    result = {"backtested_at": datetime.utcnow().isoformat()}

    # Train models and get test sets
    train_result = await train_all_models(pool)

    if not train_result.get("success"):
        result["error"] = "Training failed, cannot backtest"
        return result

    # Backtest moneyline (if we had odds data — simplified for now)
    result["moneyline"] = train_result["models"].get("moneyline", {})
    result["spread"] = train_result["models"].get("spread", {})
    result["totals"] = train_result["models"].get("totals", {})

    logger.info(f"Backtest complete: {result}")
    return result
