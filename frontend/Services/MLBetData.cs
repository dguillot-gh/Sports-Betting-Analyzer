using Microsoft.ML.Data;

namespace SportsBettingAnalyzer.Services
{
    // Separate file for ML data structure to avoid namespace issues
    public class MLBetData
    {
        [LoadColumn(0)]
        public float Odds { get; set; }

        [LoadColumn(1)]
        public float OddsFormat { get; set; }

        [LoadColumn(2)]
        public float BetType { get; set; }

        [LoadColumn(3)]
        public float Sport { get; set; }

        [LoadColumn(4)]
        public float Spread { get; set; }

        [LoadColumn(5)]
        public float OverUnder { get; set; }

        // Team/Player stats features
        [LoadColumn(6)]
        public float Team1WinRate { get; set; }

        [LoadColumn(7)]
        public float Team2WinRate { get; set; }

        [LoadColumn(8)]
        public float Team1AvgPointsFor { get; set; }

        [LoadColumn(9)]
        public float Team2AvgPointsFor { get; set; }

        [LoadColumn(10)]
        public float Team1AvgPointsAgainst { get; set; }

        [LoadColumn(11)]
        public float Team2AvgPointsAgainst { get; set; }

        // Player stats (for player props)
        [LoadColumn(12)]
        public float PlayerAvgRushingYards { get; set; }

        [LoadColumn(13)]
        public float PlayerAvgReceivingYards { get; set; }

        [LoadColumn(14)]
        public float PlayerTouchdownRate { get; set; }

        [LoadColumn(15)]
        public float PlayerAvgPoints { get; set; }

        [LoadColumn(16)]
        public float Label { get; set; }
    }
}

