using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    /// <summary>
 /// Interface for external sports data providers (APIs or web scrapers)
    /// This abstraction allows you to swap implementations without changing consuming code
    /// </summary>
    public interface IExternalDataProvider
    {
     string ProviderName { get; }
        
        Task<List<HistoricalGameResult>> GetHistoricalGamesAsync(string sport, DateTime? startDate = null, DateTime? endDate = null);
        Task<List<LiveGameData>> GetLiveGamesAsync(string sport);
    Task<TeamStats?> GetTeamStatsAsync(string teamName, string sport);
        Task<PlayerStats?> GetPlayerStatsAsync(string playerName, string sport);
        Task<bool> ValidateConnectionAsync();
    }

    /// <summary>
    /// Represents live game data for current/upcoming games
    /// </summary>
    public class LiveGameData
    {
        public string GameId { get; set; } = string.Empty;
        public string Sport { get; set; } = string.Empty;
        public string Team1 { get; set; } = string.Empty;
      public string Team2 { get; set; } = string.Empty;
        public decimal Team1Odds { get; set; }
   public decimal Team2Odds { get; set; }
        public DateTime GameTime { get; set; }
    public string Status { get; set; } = "Scheduled"; // Scheduled, InProgress, Final
        public int? Team1Score { get; set; }
        public int? Team2Score { get; set; }
    }
}
