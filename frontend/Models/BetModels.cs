namespace SportsBettingAnalyzer.Models
{
    public class BetSlip
    {
        public string? Team1 { get; set; }
        public string? Team2 { get; set; }
        public string? PlayerName { get; set; }
        public decimal Odds { get; set; }
        public string OddsFormat { get; set; } = "American"; // American, Decimal, Fractional
        public string BetType { get; set; } = "Moneyline"; // Moneyline, Spread, OverUnder, Parlay, etc.
        public decimal? Spread { get; set; }
        public decimal? OverUnder { get; set; }
        public decimal WagerAmount { get; set; }
        public decimal? PotentialWin { get; set; }
        public string Sport { get; set; } = "Unknown";
        public DateTime? GameDate { get; set; }
        public string? RawText { get; set; }
        public bool IsParlay { get; set; }
        public int ParlayLegs { get; set; }
        public List<ParlayLeg>? ParlaySelections { get; set; }
        public string? GameInfo { get; set; } // e.g., "Philadelphia Eagles @ Green Bay Packers"
    }

    public class ParlayLeg
    {
        public string PlayerName { get; set; } = string.Empty;
        public string BetDescription { get; set; } = string.Empty; // e.g., "ANY TIME TOUCHDOWN SCORER"
        public string? StatType { get; set; } // e.g., "ALT RUSHING YDS", "ALT RECEIVING YDS"
        public decimal? StatValue { get; set; } // e.g., 50, 25
        public string? StatOperator { get; set; } // e.g., "+", "over", "under"
    }

    public class BetAnalysis
    {
        public BetSlip BetSlip { get; set; } = new();
        public decimal ExpectedValue { get; set; }
        public decimal ImpliedProbability { get; set; }
        public decimal? PredictedWinProbability { get; set; }
        public decimal ValueScore { get; set; } // Positive = good bet, Negative = bad bet
        public string Recommendation { get; set; } = "Unknown"; // GoodBet, BadBet, Marginal
        public decimal ConfidenceScore { get; set; } // 0-100
        public decimal? KellyCriterion { get; set; }
        public string AnalysisDetails { get; set; } = string.Empty;
        public DateTime AnalyzedAt { get; set; } = DateTime.UtcNow;
    }

    public class HistoricalBet
    {
        public int Id { get; set; }
        public string? Team1 { get; set; }
        public string? Team2 { get; set; }
        public string? PlayerName { get; set; }
        public decimal Odds { get; set; }
        public string BetType { get; set; } = "Moneyline";
        public decimal WagerAmount { get; set; }
        public string Sport { get; set; } = "Unknown";
        public DateTime? GameDate { get; set; }
        public decimal ExpectedValue { get; set; }
        public string Recommendation { get; set; } = "Unknown";
        public decimal ConfidenceScore { get; set; }
        public bool? Won { get; set; } // Null = unknown, true = won, false = lost
        public decimal? Payout { get; set; }
        public DateTime AnalyzedAt { get; set; } = DateTime.UtcNow;
        public DateTime? ResultDate { get; set; }
    }

    public class TeamStats
    {
        public int Id { get; set; }
        public string TeamName { get; set; } = string.Empty;
        public string Sport { get; set; } = string.Empty;
        public decimal WinRate { get; set; }
        public int Wins { get; set; }
        public int Losses { get; set; }
        public decimal? AveragePointsFor { get; set; }
        public decimal? AveragePointsAgainst { get; set; }
        public DateTime LastUpdated { get; set; } = DateTime.UtcNow;
        public string? Source { get; set; }
    }
}
