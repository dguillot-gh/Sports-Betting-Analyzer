using Microsoft.ML;
using Microsoft.ML.Data;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class MLModelService
    {
        private readonly ILogger<MLModelService> _logger;
        private MLContext? _mlContext;
        private ITransformer? _model;
        private PredictionEngine<MLBetData, BetPrediction>? _predictionEngine;

        public MLModelService(ILogger<MLModelService> logger)
        {
            _logger = logger;
            InitializeMLContext();
        }

        private void InitializeMLContext()
        {
            _mlContext = new MLContext(seed: 0);
            _logger.LogInformation("ML Context initialized");
        }

        public decimal PredictWinProbability(BetSlip betSlip)
        {
            try
            {
                // If no model exists, use rule-based prediction
                if (_model == null)
                {
                    return PredictUsingRules(betSlip);
                }

                // Convert bet slip to ML data format
                var betData = ConvertToBetData(betSlip);

                // Ensure prediction engine is initialized
                if (_predictionEngine == null)
                {
                    _predictionEngine = _mlContext.Model.CreatePredictionEngine<MLBetData, BetPrediction>(_model);
                }

                // Make prediction
                var prediction = _predictionEngine.Predict(betData);
                
                // Return probability (clamped between 0 and 1)
                return Math.Max(0m, Math.Min(1m, (decimal)prediction.Probability));
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error predicting win probability");
                return PredictUsingRules(betSlip);
            }
        }

        private decimal PredictUsingRules(BetSlip betSlip)
        {
            // Rule-based prediction using implied probability from odds
            // This is a fallback when no ML model is trained
            // Calculate implied probability directly from odds
            var odds = betSlip.Odds;
            decimal probability;
            
            if (betSlip.OddsFormat == "American")
            {
                if (odds > 0)
                {
                    probability = 100m / (odds + 100m);
                }
                else
                {
                    probability = Math.Abs(odds) / (Math.Abs(odds) + 100m);
                }
            }
            else if (betSlip.OddsFormat == "Decimal")
            {
                probability = 1m / odds;
            }
            else
            {
                // Default to American format calculation
                if (odds > 0)
                {
                    probability = 100m / (odds + 100m);
                }
                else
                {
                    probability = Math.Abs(odds) / (Math.Abs(odds) + 100m);
                }
            }
            
            return probability;
        }

        private MLBetData ConvertToBetData(BetSlip betSlip)
        {
            return new MLBetData
            {
                Odds = (float)betSlip.Odds,
                OddsFormat = betSlip.OddsFormat == "American" ? 0f : 1f,
                BetType = GetBetTypeNumeric(betSlip.BetType),
                Sport = GetSportNumeric(betSlip.Sport),
                Spread = betSlip.Spread.HasValue ? (float)betSlip.Spread.Value : 0f,
                OverUnder = betSlip.OverUnder.HasValue ? (float)betSlip.OverUnder.Value : 0f,
                Team1WinRate = 0f, // Will be populated if team stats available
                Team2WinRate = 0f,
                Team1AvgPointsFor = 0f,
                Team2AvgPointsFor = 0f,
                Team1AvgPointsAgainst = 0f,
                Team2AvgPointsAgainst = 0f,
                PlayerAvgRushingYards = 0f,
                PlayerAvgReceivingYards = 0f,
                PlayerTouchdownRate = 0f,
                PlayerAvgPoints = 0f
            };
        }

        private float GetBetTypeNumeric(string betType)
        {
            return betType switch
            {
                "Moneyline" => 0f,
                "Spread" => 1f,
                "OverUnder" => 2f,
                _ => 0f
            };
        }

        private float GetSportNumeric(string sport)
        {
            return sport switch
            {
                "NFL" => 0f,
                "NBA" => 1f,
                "MLB" => 2f,
                "NHL" => 3f,
                "Soccer" => 4f,
                "NASCAR" => 5f,
                _ => 0f
            };
        }

        public void TrainModel(List<HistoricalBet>? historicalBets = null, List<MLBetData>? historicalGameData = null)
        {
            // Check if we have enough data from either source
            var betCount = historicalBets?.Count(b => b.Won.HasValue) ?? 0;
            var gameCount = historicalGameData?.Count ?? 0;
            var totalData = betCount + gameCount;

            if (totalData < 10)
            {
                _logger.LogWarning("Insufficient data for training. Have {Total} samples (bets: {BetCount}, games: {GameCount}), need 10+", 
                    totalData, betCount, gameCount);
                return;
            }

            try
            {
                if (_mlContext == null)
                {
                    InitializeMLContext();
                }

                // Convert historical bets to training data
                var betTrainingData = (historicalBets ?? new List<HistoricalBet>())
                    .Where(b => b.Won.HasValue)
                    .Select(b => new MLBetData
                    {
                        Odds = (float)b.Odds,
                        OddsFormat = 0f, // Assume American for now
                        BetType = GetBetTypeNumeric(b.BetType),
                        Sport = GetSportNumeric(b.Sport),
                        Spread = 0f,
                        OverUnder = 0f,
                        Team1WinRate = 0f, // Will be populated if team stats available
                        Team2WinRate = 0f,
                        Team1AvgPointsFor = 0f,
                        Team2AvgPointsFor = 0f,
                        Team1AvgPointsAgainst = 0f,
                        Team2AvgPointsAgainst = 0f,
                        PlayerAvgRushingYards = 0f,
                        PlayerAvgReceivingYards = 0f,
                        PlayerTouchdownRate = 0f,
                        PlayerAvgPoints = 0f,
                        Label = b.Won.Value ? 1f : 0f
                    })
                    .ToList();

                // Combine with historical game data if provided
                var trainingData = betTrainingData;
                if (historicalGameData != null && historicalGameData.Any())
                {
                    trainingData = betTrainingData.Concat(historicalGameData).ToList();
                    _logger.LogInformation("Combining {BetCount} user bets with {GameCount} historical games", 
                        betTrainingData.Count, historicalGameData.Count);
                }

                if (trainingData.Count < 10)
                {
                    _logger.LogWarning("Insufficient labeled data for training. Have {Count}, need 10+", trainingData.Count);
                    return;
                }

                // Load data
                var dataView = _mlContext.Data.LoadFromEnumerable(trainingData);

                // Define pipeline with enhanced features
                var pipeline = _mlContext.Transforms.Concatenate("Features",
                        nameof(MLBetData.Odds),
                        nameof(MLBetData.OddsFormat),
                        nameof(MLBetData.BetType),
                        nameof(MLBetData.Sport),
                        nameof(MLBetData.Spread),
                        nameof(MLBetData.OverUnder),
                        nameof(MLBetData.Team1WinRate),
                        nameof(MLBetData.Team2WinRate),
                        nameof(MLBetData.Team1AvgPointsFor),
                        nameof(MLBetData.Team2AvgPointsFor),
                        nameof(MLBetData.Team1AvgPointsAgainst),
                        nameof(MLBetData.Team2AvgPointsAgainst),
                        nameof(MLBetData.PlayerAvgRushingYards),
                        nameof(MLBetData.PlayerAvgReceivingYards),
                        nameof(MLBetData.PlayerTouchdownRate),
                        nameof(MLBetData.PlayerAvgPoints))
                    .Append(_mlContext.BinaryClassification.Trainers.FastTree(
                        labelColumnName: "Label",
                        numberOfLeaves: 30,
                        numberOfTrees: 150,
                        minimumExampleCountPerLeaf: 5));

                // Split data for training and testing (80/20)
                var splitData = _mlContext.Data.TrainTestSplit(dataView, testFraction: 0.2);
                
                // Train model on training set
                _model = pipeline.Fit(splitData.TrainSet);

                // Evaluate model on test set
                var predictions = _model.Transform(splitData.TestSet);
                var metrics = _mlContext.BinaryClassification.Evaluate(predictions, "Label");
                
                // Reset prediction engine
                _predictionEngine = null;

                _logger.LogInformation("ML model trained successfully on {Count} samples", trainingData.Count);
                _logger.LogInformation("Model Accuracy: {Accuracy:P2}, AUC: {Auc:P2}", metrics.Accuracy, metrics.AreaUnderRocCurve);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error training ML model");
            }
        }
    }

    // ML.NET data structures - using MLBetData from separate file

    public class BetPrediction
    {
        [ColumnName("PredictedLabel")]
        public bool Prediction { get; set; }

        [ColumnName("Probability")]
        public float Probability { get; set; }

        [ColumnName("Score")]
        public float Score { get; set; }
    }
}

