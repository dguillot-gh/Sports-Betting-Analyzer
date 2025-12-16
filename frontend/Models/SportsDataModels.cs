namespace SportsBettingAnalyzer.Models
{
    public class HistoricalGameResult
    {
        public int Id { get; set; }
        public string Sport { get; set; } = string.Empty;
        public string Team1 { get; set; } = string.Empty;
        public string Team2 { get; set; } = string.Empty;
        public int? Team1Score { get; set; }
        public int? Team2Score { get; set; }
        public DateTime GameDate { get; set; }
        public string? Season { get; set; }
        public int? Week { get; set; } // For NFL
        public bool? Team1Won { get; set; } // True if team1 won, false if team2 won, null if tie
        public DateTime LastUpdated { get; set; } = DateTime.UtcNow;
    }

    public class PlayerStats
    {
        public int Id { get; set; }
        public string PlayerName { get; set; } = string.Empty;
        public string Sport { get; set; } = string.Empty;
        public string? Team { get; set; }
        public string? Position { get; set; }
        
        // NFL Stats
        public decimal? AverageRushingYards { get; set; }
        public decimal? AverageReceivingYards { get; set; }
        public decimal? AveragePassingYards { get; set; }
        public decimal? TouchdownRate { get; set; } // Touchdowns per game
        public int? GamesPlayed { get; set; }
        
        // NBA Stats
        public decimal? AveragePoints { get; set; }
        public decimal? AverageRebounds { get; set; }
        public decimal? AverageAssists { get; set; }
        
        // NASCAR Stats
        public decimal? AverageFinishPosition { get; set; }
        public decimal? Top10Rate { get; set; }
        public decimal? WinRate { get; set; }
        
        public DateTime LastUpdated { get; set; } = DateTime.UtcNow;
        public string? Source { get; set; }
    }

    public class GameMatchup
    {
        public string Team1 { get; set; } = string.Empty;
        public string Team2 { get; set; } = string.Empty;
        public string Sport { get; set; } = string.Empty;
        public DateTime? GameDate { get; set; }
        public TeamStats? Team1Stats { get; set; }
        public TeamStats? Team2Stats { get; set; }
        public List<PlayerStats>? RelevantPlayers { get; set; }
    }
}

