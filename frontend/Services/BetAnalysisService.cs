using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class BetAnalysisService
    {
        private readonly BetSlipOCRService _ocrService;
        private readonly StatisticalAnalysisService _statisticalService;
        private readonly MLModelService _mlService;
        private readonly ILogger<BetAnalysisService> _logger;

        public BetAnalysisService(
            BetSlipOCRService ocrService,
            StatisticalAnalysisService statisticalService,
            MLModelService mlService,
            ILogger<BetAnalysisService> logger)
        {
            _ocrService = ocrService;
            _statisticalService = statisticalService;
            _mlService = mlService;
            _logger = logger;
        }

        public async Task<BetAnalysis> AnalyzeBetSlipImageAsync(Stream imageStream)
        {
            try
            {
                _logger.LogInformation("Starting bet slip analysis");

                // Step 1: Extract bet information from image using OCR
                var betSlip = await _ocrService.ExtractBetSlipFromImageAsync(imageStream);
                
                if (string.IsNullOrEmpty(betSlip.RawText) || betSlip.RawText == "No text extracted")
                {
                    throw new Exception("Failed to extract text from image. Please ensure the image is clear and contains readable text.");
                }

                _logger.LogInformation("Extracted bet slip: {BetType}, {Sport}, Odds: {Odds}", 
                    betSlip.BetType, betSlip.Sport, betSlip.Odds);

                // Step 2: Perform statistical analysis
                var analysis = _statisticalService.AnalyzeBet(betSlip);

                // Step 3: Get ML prediction (if model is available)
                try
                {
                    var mlPrediction = _mlService.PredictWinProbability(betSlip);
                    analysis.PredictedWinProbability = mlPrediction;

                    // Recalculate expected value with ML prediction if available
                    if (mlPrediction > 0 && mlPrediction < 1)
                    {
                        analysis.ExpectedValue = RecalculateExpectedValueWithML(
                            betSlip, 
                            mlPrediction, 
                            analysis.ExpectedValue
                        );
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "ML prediction failed, using statistical analysis only");
                }

                // Step 4: Combine results and generate final recommendation
                analysis = GenerateFinalRecommendation(analysis);

                _logger.LogInformation("Analysis complete. Recommendation: {Recommendation}, Confidence: {Confidence}%",
                    analysis.Recommendation, analysis.ConfidenceScore);

                return analysis;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error analyzing bet slip");
                throw;
            }
        }

        public BetAnalysis AnalyzeBetSlip(BetSlip betSlip)
        {
            try
            {
                // Perform statistical analysis
                var analysis = _statisticalService.AnalyzeBet(betSlip);

                // Get ML prediction
                try
                {
                    var mlPrediction = _mlService.PredictWinProbability(betSlip);
                    analysis.PredictedWinProbability = mlPrediction;

                    if (mlPrediction > 0 && mlPrediction < 1)
                    {
                        analysis.ExpectedValue = RecalculateExpectedValueWithML(
                            betSlip,
                            mlPrediction,
                            analysis.ExpectedValue
                        );
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "ML prediction failed");
                }

                // Generate final recommendation
                analysis = GenerateFinalRecommendation(analysis);

                return analysis;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error analyzing bet slip");
                throw;
            }
        }

        private decimal RecalculateExpectedValueWithML(BetSlip betSlip, decimal mlProbability, decimal originalEV)
        {
            // Recalculate EV using ML prediction instead of implied probability
            var payout = CalculatePayout(betSlip.Odds, betSlip.OddsFormat, betSlip.WagerAmount);
            var newEV = (mlProbability * payout) - betSlip.WagerAmount;
            
            // Blend with original EV (weighted average)
            return (newEV * 0.7m) + (originalEV * 0.3m);
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

        private BetAnalysis GenerateFinalRecommendation(BetAnalysis analysis)
        {
            // Combine statistical and ML insights
            var evRatio = analysis.ExpectedValue / Math.Max(analysis.BetSlip.WagerAmount, 1m);
            
            // Adjust recommendation based on ML prediction if available
            if (analysis.PredictedWinProbability.HasValue)
            {
                var mlValue = analysis.PredictedWinProbability.Value - analysis.ImpliedProbability;
                
                // If ML suggests higher probability than implied, it's a value bet
                if (mlValue > 0.05m && evRatio > 0)
                {
                    analysis.Recommendation = "GoodBet";
                    analysis.ConfidenceScore = Math.Min(100m, analysis.ConfidenceScore + 10m);
                }
                else if (mlValue < -0.05m && evRatio < 0)
                {
                    analysis.Recommendation = "BadBet";
                    analysis.ConfidenceScore = Math.Min(100m, analysis.ConfidenceScore + 10m);
                }
            }

            // Final recommendation logic
            if (analysis.ExpectedValue > analysis.BetSlip.WagerAmount * 0.15m)
            {
                analysis.Recommendation = "GoodBet";
            }
            else if (analysis.ExpectedValue < -analysis.BetSlip.WagerAmount * 0.15m)
            {
                analysis.Recommendation = "BadBet";
            }
            else if (analysis.ExpectedValue > 0)
            {
                analysis.Recommendation = "Marginal";
            }
            else
            {
                analysis.Recommendation = "BadBet";
            }

            // Update analysis details
            if (analysis.PredictedWinProbability.HasValue)
            {
                analysis.AnalysisDetails += $"\nML Predicted Win Probability: {analysis.PredictedWinProbability.Value:P2}";
                var difference = analysis.PredictedWinProbability.Value - analysis.ImpliedProbability;
                analysis.AnalysisDetails += $"\nML vs Implied Difference: {difference:P2}";
            }

            return analysis;
        }
    }
}

