using System.Text.Json.Serialization;

namespace SportsBettingAnalyzer.Models
{
    public class AiQuota
    {
        [JsonPropertyName("used")]
        public int Used { get; set; }
        
        [JsonPropertyName("limit")]
        public int Limit { get; set; }
        
        [JsonPropertyName("remaining")]
        public int Remaining { get; set; }
    }

    public class AiEnginePrediction
    {
        [JsonPropertyName("home_win_prob")]
        public double HomeWinProb { get; set; }
        
        [JsonPropertyName("home_score")]
        public double HomeScore { get; set; }
        
        [JsonPropertyName("away_score")]
        public double AwayScore { get; set; }

        [JsonPropertyName("description")]
        public string Description { get; set; } = "";
        
        [JsonPropertyName("explanation")]
        public System.Text.Json.JsonElement? Explanation { get; set; }
    }

    public class AiInsight
    {
        [JsonPropertyName("winner")]
        public string Winner { get; set; } = "";
        
        [JsonPropertyName("confidence")]
        public double Confidence { get; set; }
        
        [JsonPropertyName("rationale")]
        public string Rationale { get; set; } = "";
        
        [JsonPropertyName("key_factor")]
        public string KeyFactor { get; set; } = "";
    }

    public class AiAnalysisReport
    {
        [JsonPropertyName("sport")]
        public string Sport { get; set; } = "";
        
        [JsonPropertyName("matchup")]
        public string Matchup { get; set; } = "";
        
        [JsonPropertyName("engines")]
        public Dictionary<string, AiEnginePrediction> Engines { get; set; } = new();
        
        [JsonPropertyName("llm_insight")]
        public AiInsight? LlmInsight { get; set; }
    }

    public class DashboardModelSummary
    {
        [JsonPropertyName("sport")]
        public string Sport { get; set; } = "";
        
        [JsonPropertyName("series")]
        public string Series { get; set; } = "";
        
        [JsonPropertyName("task")]
        public string Task { get; set; } = "";
        
        [JsonPropertyName("accuracy")]
        public double Accuracy { get; set; }
        
        [JsonPropertyName("precision")]
        public double Precision { get; set; }
        
        [JsonPropertyName("roi")]
        public double Roi { get; set; }
        
        [JsonPropertyName("last_updated")]
        public double LastUpdated { get; set; }
    }

    public class EnhanceResponse
    {
        [JsonPropertyName("success")]
        public bool Success { get; set; }

        [JsonPropertyName("message")]
        public string? Message { get; set; }

        [JsonPropertyName("series_enhanced")]
        public List<string>? SeriesEnhanced { get; set; }

        [JsonPropertyName("total_records")]
        public int? TotalRecords { get; set; }
    }

    public class NascarRacePredictions
    {
        [JsonPropertyName("race_id")]
        public int RaceId { get; set; }

        [JsonPropertyName("track_name")]
        public string TrackName { get; set; } = "";

        [JsonPropertyName("prediction_count")]
        public int PredictionCount { get; set; }

        [JsonPropertyName("confidence")]
        public string Confidence { get; set; } = "";

        [JsonPropertyName("predictions")]
        public List<NascarDriverPrediction> Predictions { get; set; } = new();
    }

    public class NascarDriverPrediction
    {
        [JsonPropertyName("driver_name")]
        public string DriverName { get; set; } = "";

        [JsonPropertyName("car_number")]
        public string CarNumber { get; set; } = "";

        [JsonPropertyName("win_probability")]
        public double WinProbability { get; set; }

        [JsonPropertyName("projected_finish")]
        public double ProjectedFinish { get; set; }

        [JsonPropertyName("market_odds")]
        public string MarketOdds { get; set; } = "";

        [JsonPropertyName("engines")]
        public Dictionary<string, object> Engines { get; set; } = new();

        [JsonPropertyName("confidence")]
        public string Confidence { get; set; } = "";
        
        [JsonPropertyName("rank")]
        public int Rank { get; set; }
    }

    public class HitRateResult
    {
        [JsonPropertyName("team")] 
        public string Team { get; set; } = "";
        
        [JsonPropertyName("metric")] 
        public string Metric { get; set; } = "";
        
        [JsonPropertyName("line")] 
        public double Line { get; set; }
        
        [JsonPropertyName("games_analyzed")] 
        public int GamesAnalyzed { get; set; }
        
        [JsonPropertyName("hits")] 
        public int Hits { get; set; }
        
        [JsonPropertyName("hit_rate")] 
        public double HitRate { get; set; }
        
        [JsonPropertyName("avg_value")] 
        public double AvgValue { get; set; }
        
        [JsonPropertyName("game_log")] 
        public List<HitRateGameLog> GameLog { get; set; } = new();
    }

    public class HitRateGameLog
    {
        [JsonPropertyName("date")] 
        public string Date { get; set; } = "";
        
        [JsonPropertyName("opponent")] 
        public string Opponent { get; set; } = "";
        
        [JsonPropertyName("score")] 
        public string Score { get; set; } = "";
        
        [JsonPropertyName("value")] 
        public double Value { get; set; }
        
        [JsonPropertyName("is_hit")] 
        public bool IsHit { get; set; }
    }

    public class EspnResponse
    {
        [JsonPropertyName("sport")]
        public string Sport { get; set; } = "";
        
        [JsonPropertyName("source")]
        public string Source { get; set; } = "";
        
        [JsonPropertyName("week")]
        public int? Week { get; set; }
        
        [JsonPropertyName("disclaimer")]
        public string Disclaimer { get; set; } = "";
        
        [JsonPropertyName("games")]
        public List<EspnGame> Games { get; set; } = new();
    }

    public class EspnGame
    {
        [JsonPropertyName("event_id")]
        public string EventId { get; set; } = "";
        
        [JsonPropertyName("game_time")]
        public string GameTime { get; set; } = "";
        
        [JsonPropertyName("home_team")]
        public string HomeTeam { get; set; } = "";
        
        [JsonPropertyName("away_team")]
        public string AwayTeam { get; set; } = "";
        
        [JsonPropertyName("home_score")]
        public string HomeScore { get; set; } = "";
        
        [JsonPropertyName("away_score")]
        public string AwayScore { get; set; } = "";
        
        [JsonPropertyName("home_rank")]
        public object? HomeRank { get; set; }
        
        [JsonPropertyName("away_rank")]
        public object? AwayRank { get; set; }
        
        [JsonPropertyName("home_win_prob")]
        public double HomeWinProb { get; set; }
        
        [JsonPropertyName("away_win_prob")]
        public double AwayWinProb { get; set; }
        
        [JsonPropertyName("total_over_prob")]
        public double TotalOverProb { get; set; }
        
        [JsonPropertyName("spread")]
        public string Spread { get; set; } = "";
        
        [JsonPropertyName("over_under")]
        public double? OverUnder { get; set; }
    }

    public class BacktestReport
    {
        [JsonPropertyName("total_games")]
        public int TotalGames { get; set; }
        
        [JsonPropertyName("bets_placed")]
        public int BetsPlaced { get; set; }
        
        [JsonPropertyName("wins")]
        public int Wins { get; set; }
        
        [JsonPropertyName("losses")]
        public int Losses { get; set; }
        
        [JsonPropertyName("hit_rate")]
        public double HitRate { get; set; }
        
        [JsonPropertyName("units_won")]
        public double UnitsWon { get; set; }
        
        [JsonPropertyName("roi_percent")]
        public double RoiPercent { get; set; }
        
        [JsonPropertyName("daily_pnl")]
        public Dictionary<string, double>? DailyPnl { get; set; }
    }
}
