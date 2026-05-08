import sys
import os
import asyncio
import random
import argparse
from datetime import datetime, timedelta

# Add the backend directory to sys.path so we can import services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.notifications import NotificationService
from src.config import DATABASE_URL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, REPORT_EMAIL_TO
import smtplib
from email.message import EmailMessage

SPORTS = ["ncaab", "nba", "nfl", "nascar", "nhl", "baseball", "mlb_results", "cfb"]

def send_test_report_email(subject: str, body: str):
    """Sends a plain text email containing the chaos test results."""
    if not REPORT_EMAIL_TO or not SMTP_USER:
        print("⚠️ Email config missing, cannot send test report via email.")
        return
        
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = REPORT_EMAIL_TO
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"📧 Test execution report successfully emailed to {REPORT_EMAIL_TO}")
    except Exception as e:
        print(f"❌ Failed to email test report: {e}")

def _make_result(sport: str, success: bool, rows: int = 0, new: int = 0, error: str = "") -> dict:
    """Build a fake import result dict matching the real pipeline format."""
    duration = round(random.uniform(1.0, 45.0), 1)
    result = {
        "sport": sport,
        "success": success,
        "duration": duration,
        "rows": rows,
        "new": new,
        "updated": max(0, rows - new),
        "_records": [],
    }
    if error:
        result["error"] = error
        result["rows"] = 0
        result["new"] = 0
        result["updated"] = 0
    return result

async def run_notifications_chaos(scenario: str):
    print(f"🔔 Running Notification Chaos: {scenario.upper()} scenario")
    
    fake_results = []
    for sport in SPORTS:
        if scenario == "all_healthy":
            fake_results.append(_make_result(sport, success=True, rows=random.randint(50, 500), new=random.randint(5, 50)))
        elif scenario == "some_stale":
            is_stale = sport in random.sample(SPORTS, 3)
            if is_stale:
                fake_results.append(_make_result(sport, success=True, rows=random.randint(100, 1000), new=0))
            else:
                fake_results.append(_make_result(sport, success=True, rows=random.randint(50, 500), new=random.randint(5, 50)))
        elif scenario == "some_failed":
            is_failed = sport in random.sample(SPORTS, 2)
            if is_failed:
                fake_results.append(_make_result(sport, success=False, error=f"Simulated failure: Connection refused from {sport} data source"))
            else:
                fake_results.append(_make_result(sport, success=True, rows=random.randint(50, 500), new=random.randint(5, 50)))
        else:  # chaos
            roll = random.random()
            if roll < 0.25:
                fake_results.append(_make_result(sport, success=False, error=f"Chaos: {random.choice(['Timeout', 'ConnectionRefused', 'RateLimited', '500 Internal Server Error'])}"))
            elif roll < 0.50:
                fake_results.append(_make_result(sport, success=True, rows=random.randint(100, 2000), new=0))
            else:
                fake_results.append(_make_result(sport, success=True, rows=random.randint(50, 500), new=random.randint(5, 50)))

    fake_perf = {"total": 12, "wins": 7, "losses": 5, "profit": -23.50, "roi": -4.7, "db_total_rows": 184520}
    
    await NotificationService.send_summary_report(
        results=fake_results,
        perf_summary=fake_perf,
        import_records=[],
    )
    
    success_count = sum(1 for r in fake_results if r.get("success"))
    fail_count = len(fake_results) - success_count
    stale_count = sum(1 for r in fake_results if r.get("success") and r.get("rows", 0) > 0 and r.get("new", 0) == 0)
    email_sent = fail_count > 0 or stale_count > 0

    summary = (
        f"🐒 Chaos Monkey Execution: NOTIFICATIONS ({scenario.upper()})\n\n"
        f"📊 Summary:\n"
        f"  Total: {len(fake_results)}\n"
        f"  Success: {success_count}\n"
        f"  Failed: {fail_count}\n"
        f"  Stale: {stale_count}\n"
        f"  📧 Pipeline Email Triggered: {email_sent}\n\n"
        f"Result Breakdown:\n"
    )
    for r in fake_results:
        summary += f" - {r['sport']}: success={r.get('success')}, rows={r.get('rows', 0)}, new={r.get('new', 0)} {r.get('error', '')}\n"

    print(summary)
    send_test_report_email(f"🐒 Chaos Monkey Report: Notifications [{scenario.upper()}]", summary)

async def run_bet_grader_chaos(scenario: str):
    import asyncpg
    print(f"💰 Running Bet Grader Chaos: {scenario.upper()} scenario")
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Generate fake bets over the last 7 days
        now = datetime.now()
        fake_bets = []
        
        for i in range(7):
            date = now - timedelta(days=6 - i)
            num_bets = random.randint(5, 15)
            
            for _ in range(num_bets):
                stake = random.uniform(50, 500)
                odds = random.choice([-110, -110, -110, 150, 200, -200])
                
                if scenario == "massive_wins":
                    outcome = "win" if random.random() < 0.9 else "loss"
                    stake = random.uniform(500, 2000)
                elif scenario == "devastating_losses":
                    outcome = "loss" if random.random() < 0.9 else "win"
                    stake = random.uniform(500, 2000)
                elif scenario == "extreme_volatility":
                    outcome = "win" if random.random() < 0.5 else "loss"
                    stake = random.uniform(1000, 5000)
                else: # normal
                    outcome = "win" if random.random() < 0.52 else "loss"
                
                # Calculate profit
                if outcome == "win":
                    profit = stake * (100 / abs(odds)) if odds < 0 else stake * (odds / 100)
                elif outcome == "loss":
                    profit = -stake
                else:
                    profit = 0
                
                fake_bets.append({
                    "sport": random.choice(["nfl", "nba", "mlb"]),
                    "bet_type": "single",
                    "stake": stake,
                    "odds": odds,
                    "potential_payout": stake + (profit if profit > 0 else 0),
                    "outcome": outcome,
                    "profit": profit,
                    "game_name": "Chaos Monkey Game",
                    "pick": f"Simulated {scenario} bet",
                    "source": "chaos_monkey",
                    "game_date": date,
                    "created_at": date,
                    "is_mock": True
                })
        
        # Insert bets
        inserted = 0
        for b in fake_bets:
            await conn.execute("""
                INSERT INTO bets (sport, bet_type, stake, odds, potential_payout, 
                                 outcome, profit, game_name, pick, source, game_date, created_at, is_mock)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """, b["sport"], b["bet_type"], b["stake"], b["odds"], b["potential_payout"],
                b["outcome"], b["profit"], b["game_name"], b["pick"], b["source"], b["game_date"], b["created_at"], b["is_mock"])
            inserted += 1
            
        summary = (
            f"🐒 Chaos Monkey Execution: BET GRADER ({scenario.upper()})\n\n"
            f"📊 Summary:\n"
            f"  Inserted {inserted} fake bets into the database.\n\n"
            f"  Check the mobile app Data Health and Home page to see the chart react!\n"
            f"  (Note: these are marked is_mock=True, so you can delete them later by filtering for mock bets)\n"
        )
        print(summary)
        send_test_report_email(f"🐒 Chaos Monkey Report: Bet Grader [{scenario.upper()}]", summary)
        
    finally:
        await conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chaos Monkey testing tool.")
    parser.add_argument("--module", choices=["notifications", "bet_grader", "all"], default="all", help="Which system to test.")
    parser.add_argument("scenario", nargs="?", default="chaos", help="The test scenario to run.")
    args = parser.parse_args()
    
    if args.module in ["notifications", "all"]:
        notif_scenario = args.scenario if args.scenario in ["all_healthy", "some_stale", "some_failed", "chaos"] else "chaos"
        asyncio.run(run_notifications_chaos(notif_scenario))
        
    if args.module in ["bet_grader", "all"]:
        bet_scenario = args.scenario if args.scenario in ["massive_wins", "devastating_losses", "extreme_volatility", "normal"] else "extreme_volatility"
        asyncio.run(run_bet_grader_chaos(bet_scenario))
