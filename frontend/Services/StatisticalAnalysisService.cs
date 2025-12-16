using MathNet.Numerics.Distributions;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class StatisticalAnalysisService
    {
        private readonly ILogger<StatisticalAnalysisService> _logger;

        public StatisticalAnalysisService(ILogger<StatisticalAnalysisService> logger)
        {
            _logger = logger;
        }

        public BetAnalysis AnalyzeBet(BetSlip betSlip)
        {
            var analysis = new BetAnalysis
            {
                BetSlip = betSlip,
                AnalyzedAt = DateTime.UtcNow
            };

            try
            {
                // For parlays, use different analysis approach
                if (betSlip.IsParlay)
                {
                    return AnalyzeParlay(betSlip, analysis);
                }

                // Convert odds to implied probability
                analysis.ImpliedProbability = ConvertOddsToProbability(betSlip.Odds, betSlip.OddsFormat);

                // Calculate expected value
                analysis.ExpectedValue = CalculateExpectedValue(
                    betSlip.Odds,
                    betSlip.OddsFormat,
                    betSlip.WagerAmount,
                    analysis.ImpliedProbability
                );

                // Calculate value score (difference between true probability and implied probability)
                // For now, we'll use implied probability as baseline (assuming no external data)
                // In a real system, you'd compare against predicted probability from ML model
                analysis.ValueScore = analysis.ExpectedValue / betSlip.WagerAmount * 100;

                // Calculate Kelly Criterion for optimal bet sizing
                // Use predicted probability if available (from ML), otherwise use implied probability
                // Note: Kelly with implied probability will typically be 0% since there's no edge
                var probabilityForKelly = analysis.PredictedWinProbability ?? analysis.ImpliedProbability;
                if (probabilityForKelly > 0 && probabilityForKelly < 1)
                {
                    analysis.KellyCriterion = CalculateKellyCriterion(
                        probabilityForKelly,
                        betSlip.Odds,
                        betSlip.OddsFormat
                    );
                }

                // Generate recommendation
                analysis.Recommendation = GenerateRecommendation(analysis);
                analysis.ConfidenceScore = CalculateConfidenceScore(analysis);

                // Build analysis details
                analysis.AnalysisDetails = BuildAnalysisDetails(analysis);

                return analysis;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error analyzing bet");
                analysis.Recommendation = "Error";
                analysis.AnalysisDetails = $"Error during analysis: {ex.Message}";
                return analysis;
            }
        }

        private BetAnalysis AnalyzeParlay(BetSlip betSlip, BetAnalysis analysis)
        {
            // For parlays, the implied probability is typically very low due to multiple legs
            analysis.ImpliedProbability = ConvertOddsToProbability(betSlip.Odds, betSlip.OddsFormat);

            // Calculate expected value using potential win if available
            if (betSlip.PotentialWin.HasValue)
            {
                analysis.ExpectedValue = (analysis.ImpliedProbability * betSlip.PotentialWin.Value) - betSlip.WagerAmount;
            }
            else
            {
                // Calculate potential win from odds
                var payout = CalculatePayout(betSlip.Odds, betSlip.OddsFormat, betSlip.WagerAmount);
                analysis.ExpectedValue = (analysis.ImpliedProbability * payout) - betSlip.WagerAmount;
            }

            // Parlays have inherently lower win probability but higher payouts
            // Adjust value score calculation for parlays
            analysis.ValueScore = analysis.ExpectedValue / betSlip.WagerAmount * 100;

            // Note: Kelly Criterion for parlays is more complex and typically lower
            // For simplicity, we'll skip it for parlays or use a conservative estimate
            if (analysis.ImpliedProbability > 0 && analysis.ImpliedProbability < 1)
            {
                // Use a more conservative Kelly for parlays (cap at 5% of bankroll)
                var baseKelly = CalculateKellyCriterion(
                    analysis.ImpliedProbability,
                    betSlip.Odds,
                    betSlip.OddsFormat
                );
                analysis.KellyCriterion = Math.Min(baseKelly, 0.05m);
            }

            // Generate recommendation (parlays are generally riskier)
            analysis.Recommendation = GenerateParlayRecommendation(analysis, betSlip);
            analysis.ConfidenceScore = CalculateConfidenceScore(analysis);

            // Build analysis details with parlay-specific info
            analysis.AnalysisDetails = BuildParlayAnalysisDetails(analysis, betSlip);

            return analysis;
        }

        private string GenerateParlayRecommendation(BetAnalysis analysis, BetSlip betSlip)
        {
            // Parlays are inherently riskier - adjust thresholds
            var evRatio = analysis.ExpectedValue / Math.Max(betSlip.WagerAmount, 1m);
            
            // For parlays, require higher EV to be considered "Good"
            if (evRatio > 0.2m && analysis.ImpliedProbability > 0.05m) // At least 5% implied probability
            {
                return "GoodBet";
            }
            else if (evRatio < -0.1m || analysis.ImpliedProbability < 0.02m)
            {
                return "BadBet";
            }
            else
            {
                return "Marginal";
            }
        }

        private string BuildParlayAnalysisDetails(BetAnalysis analysis, BetSlip betSlip)
        {
            var details = new System.Text.StringBuilder();
            details.AppendLine($"Parlay with {betSlip.ParlayLegs} legs");
            details.AppendLine($"Implied Probability: {analysis.ImpliedProbability:P2}");
            details.AppendLine($"Expected Value: ${analysis.ExpectedValue:F2}");
            
            if (betSlip.PotentialWin.HasValue)
            {
                details.AppendLine($"Potential Win: ${betSlip.PotentialWin.Value:F2}");
            }
            
            if (analysis.KellyCriterion.HasValue)
            {
                details.AppendLine($"Recommended Bet Size: {analysis.KellyCriterion.Value:P2} of bankroll (conservative for parlays)");
            }
            
            details.AppendLine($"Value Score: {analysis.ValueScore:F2}");
            details.AppendLine($"Confidence: {analysis.ConfidenceScore:F0}%");
            details.AppendLine("\nNote: Parlays have lower win probability but higher payouts. Consider the risk/reward carefully.");
            
            return details.ToString();
        }

        private decimal ConvertOddsToProbability(decimal odds, string format)
        {
            return format switch
            {
                "American" => ConvertAmericanOddsToProbability(odds),
                "Decimal" => 1m / odds,
                "Fractional" => ConvertFractionalOddsToProbability(odds),
                _ => ConvertAmericanOddsToProbability(odds) // Default to American
            };
        }

        private decimal ConvertAmericanOddsToProbability(decimal odds)
        {
            if (odds > 0)
            {
                return 100m / (odds + 100m);
            }
            else
            {
                return Math.Abs(odds) / (Math.Abs(odds) + 100m);
            }
        }

        private decimal ConvertFractionalOddsToProbability(decimal odds)
        {
            // Assuming odds is stored as decimal representation of fraction (e.g., 3/2 = 1.5)
            return 1m / (odds + 1m);
        }

        private decimal CalculateExpectedValue(decimal odds, string format, decimal wager, decimal probability)
        {
            var payout = CalculatePayout(odds, format, wager);
            var expectedValue = (probability * payout) - wager;
            return expectedValue;
        }

        private decimal CalculatePayout(decimal odds, string format, decimal wager)
        {
            return format switch
            {
                "American" => CalculateAmericanPayout(odds, wager),
                "Decimal" => wager * odds,
                "Fractional" => wager * (odds + 1m),
                _ => CalculateAmericanPayout(odds, wager)
            };
        }

        private decimal CalculateAmericanPayout(decimal odds, decimal wager)
        {
            if (odds > 0)
            {
                return wager * (odds / 100m) + wager;
            }
            else
            {
                return wager * (100m / Math.Abs(odds)) + wager;
            }
        }

        private decimal CalculateKellyCriterion(decimal winProbability, decimal odds, string format)
        {
            // Kelly Criterion: f = (bp - q) / b
            // where b = odds, p = win probability, q = loss probability
            var payout = CalculatePayout(odds, format, 1m);
            var b = payout - 1m; // Net odds
            var p = winProbability;
            var q = 1m - p;

            if (b <= 0 || p <= 0)
                return 0m;

            var kelly = (b * p - q) / b;
            
            // Cap at 25% of bankroll for safety
            return Math.Max(0m, Math.Min(kelly, 0.25m));
        }

        private string GenerateRecommendation(BetAnalysis analysis)
        {
            if (analysis.ExpectedValue > analysis.BetSlip.WagerAmount * 0.1m)
            {
                return "GoodBet";
            }
            else if (analysis.ExpectedValue < -analysis.BetSlip.WagerAmount * 0.1m)
            {
                return "BadBet";
            }
            else
            {
                return "Marginal";
            }
        }

        private decimal CalculateConfidenceScore(BetAnalysis analysis)
        {
            // Base confidence on how clear the recommendation is
            var evRatio = analysis.ExpectedValue / Math.Max(analysis.BetSlip.WagerAmount, 1m);
            var confidence = Math.Min(100m, Math.Max(0m, 50m + (evRatio * 100m)));
            
            // Adjust based on odds format and data quality
            if (analysis.BetSlip.Odds == 0)
                confidence *= 0.5m;
            
            return confidence;
        }

        private string BuildAnalysisDetails(BetAnalysis analysis)
        {
            var details = new System.Text.StringBuilder();
            details.AppendLine($"Implied Probability (from odds): {analysis.ImpliedProbability:P2}");
            
            if (analysis.PredictedWinProbability.HasValue)
            {
                details.AppendLine($"Predicted Win Probability (ML): {analysis.PredictedWinProbability.Value:P2}");
                var edge = analysis.PredictedWinProbability.Value - analysis.ImpliedProbability;
                details.AppendLine($"Edge: {edge:P2} (positive = value bet)");
            }
            else
            {
                details.AppendLine("Note: Using implied probability (no ML prediction available)");
            }
            
            details.AppendLine($"Expected Value: ${analysis.ExpectedValue:F2}");
            
            if (analysis.KellyCriterion.HasValue)
            {
                if (analysis.KellyCriterion.Value == 0m)
                {
                    details.AppendLine($"Kelly Criterion: 0.00% (no edge detected - bet is fairly priced)");
                    details.AppendLine("  → This means the odds match the true probability, so no optimal bet size");
                }
                else
                {
                    details.AppendLine($"Kelly Criterion: {analysis.KellyCriterion.Value:P2} of bankroll");
                    details.AppendLine($"  → Recommended bet: {analysis.KellyCriterion.Value:P2} of your total bankroll");
                    details.AppendLine($"  → For a $1000 bankroll: ${(analysis.KellyCriterion.Value * 1000m):F2}");
                }
            }
            
            details.AppendLine($"Value Score: {analysis.ValueScore:F2}");
            details.AppendLine($"Confidence: {analysis.ConfidenceScore:F0}%");
            
            return details.ToString();
        }
    }
}

