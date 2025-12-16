using Microsoft.EntityFrameworkCore;
using SportsBettingAnalyzer.Data;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class SportsDataService
    {
        private readonly ApplicationDbContext _context;
        private readonly ILogger<SportsDataService> _logger;
        private readonly StatsScraperService _scraperService;

        public SportsDataService(
            ApplicationDbContext context,
            ILogger<SportsDataService> logger,
            StatsScraperService scraperService)
        {
            _context = context;
            _logger = logger;
            _scraperService = scraperService;
        }

        public async Task<List<HistoricalGameResult>> GetHistoricalGamesAsync(string sport, int? limit = null)
        {
            try
            {
                var query = _context.HistoricalGameResults
                    .Where(g => g.Sport == sport)
                    .OrderByDescending(g => g.GameDate)
                    .AsQueryable();

                if (limit.HasValue)
                {
                    query = query.Take(limit.Value);
                }

                return await query.ToListAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error retrieving historical games for {Sport}", sport);
                return new List<HistoricalGameResult>();
            }
        }

        public async Task<List<HistoricalGameResult>> GetGamesForTrainingAsync(string sport)
        {
            try
            {
                // Get games with complete results (scores and winner)
                return await _context.HistoricalGameResults
                    .Where(g => g.Sport == sport && 
                                g.Team1Score.HasValue && 
                                g.Team2Score.HasValue && 
                                g.Team1Won.HasValue)
                    .OrderByDescending(g => g.GameDate)
                    .ToListAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error retrieving games for training");
                return new List<HistoricalGameResult>();
            }
        }

        public async Task<TeamStats?> GetOrFetchTeamStatsAsync(string teamName, string sport)
        {
            try
            {
                // Check database first
                var existing = await _context.TeamStats
                    .FirstOrDefaultAsync(t => t.TeamName == teamName && t.Sport == sport);

                // If exists and recent (within 24 hours), return it
                if (existing != null && existing.LastUpdated > DateTime.UtcNow.AddHours(-24))
                {
                    return existing;
                }

                // Otherwise, try to fetch from scraper
                var stats = await _scraperService.GetTeamStatsAsync(teamName, sport);
                if (stats != null)
                {
                    if (existing != null)
                    {
                        // Update existing
                        existing.WinRate = stats.WinRate;
                        existing.Wins = stats.Wins;
                        existing.Losses = stats.Losses;
                        existing.AveragePointsFor = stats.AveragePointsFor;
                        existing.AveragePointsAgainst = stats.AveragePointsAgainst;
                        existing.LastUpdated = DateTime.UtcNow;
                        existing.Source = stats.Source;
                    }
                    else
                    {
                        // Add new
                        _context.TeamStats.Add(stats);
                    }

                    await _context.SaveChangesAsync();
                    return stats;
                }

                return existing; // Return cached if fetch failed
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error getting team stats for {Team} in {Sport}", teamName, sport);
                return null;
            }
        }

        public async Task<PlayerStats?> GetOrFetchPlayerStatsAsync(string playerName, string sport)
        {
            try
            {
                // Check database first
                var existing = await _context.PlayerStats
                    .FirstOrDefaultAsync(p => p.PlayerName == playerName && p.Sport == sport);

                // If exists and recent (within 24 hours), return it
                if (existing != null && existing.LastUpdated > DateTime.UtcNow.AddHours(-24))
                {
                    return existing;
                }

                // Otherwise, try to fetch from scraper
                var stats = await _scraperService.GetPlayerStatsAsync(playerName, sport);
                if (stats != null)
                {
                    if (existing != null)
                    {
                        // Update existing stats
                        UpdatePlayerStats(existing, stats);
                        existing.LastUpdated = DateTime.UtcNow;
                    }
                    else
                    {
                        _context.PlayerStats.Add(stats);
                    }

                    await _context.SaveChangesAsync();
                    return stats;
                }

                return existing; // Return cached if fetch failed
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error getting player stats for {Player} in {Sport}", playerName, sport);
                return null;
            }
        }

        private void UpdatePlayerStats(PlayerStats existing, PlayerStats updated)
        {
            existing.AverageRushingYards = updated.AverageRushingYards;
            existing.AverageReceivingYards = updated.AverageReceivingYards;
            existing.AveragePassingYards = updated.AveragePassingYards;
            existing.TouchdownRate = updated.TouchdownRate;
            existing.GamesPlayed = updated.GamesPlayed;
            existing.AveragePoints = updated.AveragePoints;
            existing.AverageRebounds = updated.AverageRebounds;
            existing.AverageAssists = updated.AverageAssists;
            existing.AverageFinishPosition = updated.AverageFinishPosition;
            existing.Top10Rate = updated.Top10Rate;
            existing.WinRate = updated.WinRate;
            existing.Team = updated.Team;
            existing.Position = updated.Position;
            existing.Source = updated.Source;
        }

        public async Task SaveGameResultAsync(HistoricalGameResult gameResult)
        {
            try
            {
                // Check if already exists
                var existing = await _context.HistoricalGameResults
                    .FirstOrDefaultAsync(g => g.Sport == gameResult.Sport &&
                                               g.Team1 == gameResult.Team1 &&
                                               g.Team2 == gameResult.Team2 &&
                                               g.GameDate.Date == gameResult.GameDate.Date);

                if (existing != null)
                {
                    // Update existing
                    existing.Team1Score = gameResult.Team1Score;
                    existing.Team2Score = gameResult.Team2Score;
                    existing.Team1Won = gameResult.Team1Won;
                    existing.LastUpdated = DateTime.UtcNow;
                }
                else
                {
                    _context.HistoricalGameResults.Add(gameResult);
                }

                await _context.SaveChangesAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error saving game result");
                throw;
            }
        }

        public async Task<List<HistoricalGameResult>> GetRecentGamesForTeamsAsync(string team1, string team2, string sport, int days = 30)
        {
            try
            {
                var cutoffDate = DateTime.UtcNow.AddDays(-days);
                return await _context.HistoricalGameResults
                    .Where(g => g.Sport == sport &&
                                g.GameDate >= cutoffDate &&
                                ((g.Team1 == team1 && g.Team2 == team2) ||
                                 (g.Team1 == team2 && g.Team2 == team1)))
                    .OrderByDescending(g => g.GameDate)
                    .ToListAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error retrieving recent games");
                return new List<HistoricalGameResult>();
            }
        }
    }
}

