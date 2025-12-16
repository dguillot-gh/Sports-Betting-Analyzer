using Microsoft.EntityFrameworkCore;
using SportsBettingAnalyzer.Data;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class DataCollectionService
    {
        private readonly ApplicationDbContext _context;
        private readonly ILogger<DataCollectionService> _logger;

        public DataCollectionService(ApplicationDbContext context, ILogger<DataCollectionService> logger)
        {
            _context = context;
            _logger = logger;
        }

        public async Task SaveBetAnalysisAsync(BetAnalysis analysis)
        {
            try
            {
                var historicalBet = new HistoricalBet
                {
                    Team1 = analysis.BetSlip.Team1,
                    Team2 = analysis.BetSlip.Team2,
                    PlayerName = analysis.BetSlip.PlayerName,
                    Odds = analysis.BetSlip.Odds,
                    BetType = analysis.BetSlip.BetType,
                    WagerAmount = analysis.BetSlip.WagerAmount,
                    Sport = analysis.BetSlip.Sport,
                    GameDate = analysis.BetSlip.GameDate,
                    ExpectedValue = analysis.ExpectedValue,
                    Recommendation = analysis.Recommendation,
                    ConfidenceScore = analysis.ConfidenceScore,
                    AnalyzedAt = analysis.AnalyzedAt
                };

                _context.HistoricalBets.Add(historicalBet);
                await _context.SaveChangesAsync();

                _logger.LogInformation("Saved bet analysis with ID {Id}", historicalBet.Id);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error saving bet analysis");
                throw;
            }
        }

        public async Task UpdateBetResultAsync(int betId, bool won, decimal? payout = null)
        {
            try
            {
                var bet = await _context.HistoricalBets.FindAsync(betId);
                if (bet == null)
                {
                    _logger.LogWarning("Bet with ID {Id} not found", betId);
                    return;
                }

                bet.Won = won;
                bet.Payout = payout;
                bet.ResultDate = DateTime.UtcNow;

                await _context.SaveChangesAsync();
                _logger.LogInformation("Updated bet result for ID {Id}: Won = {Won}", betId, won);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error updating bet result");
                throw;
            }
        }

        public async Task<List<HistoricalBet>> GetHistoricalBetsAsync(int? limit = null)
        {
            try
            {
                var query = _context.HistoricalBets
                    .OrderByDescending(b => b.AnalyzedAt)
                    .AsQueryable();

                if (limit.HasValue)
                {
                    query = query.Take(limit.Value);
                }

                return await query.ToListAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error retrieving historical bets");
                throw;
            }
        }

        public async Task<List<HistoricalBet>> GetBetsForTrainingAsync()
        {
            try
            {
                // Get bets that have results (won/lost) for ML training
                return await _context.HistoricalBets
                    .Where(b => b.Won.HasValue)
                    .OrderByDescending(b => b.AnalyzedAt)
                    .ToListAsync();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error retrieving bets for training");
                return new List<HistoricalBet>();
            }
        }

        public async Task<Dictionary<string, object>> GetAnalyticsAsync()
        {
            try
            {
                var totalBets = await _context.HistoricalBets.CountAsync();
                var betsWithResults = await _context.HistoricalBets
                    .Where(b => b.Won.HasValue)
                    .CountAsync();
                
                var wonBets = await _context.HistoricalBets
                    .Where(b => b.Won == true)
                    .CountAsync();

                var totalWagered = await _context.HistoricalBets
                    .SumAsync(b => b.WagerAmount);

                var totalPayout = await _context.HistoricalBets
                    .Where(b => b.Payout.HasValue)
                    .SumAsync(b => b.Payout ?? 0);

                var goodBetCount = await _context.HistoricalBets
                    .Where(b => b.Recommendation == "GoodBet")
                    .CountAsync();

                var analytics = new Dictionary<string, object>
                {
                    { "TotalBets", totalBets },
                    { "BetsWithResults", betsWithResults },
                    { "WonBets", wonBets },
                    { "WinRate", betsWithResults > 0 ? (double)wonBets / betsWithResults : 0 },
                    { "TotalWagered", totalWagered },
                    { "TotalPayout", totalPayout },
                    { "NetProfit", totalPayout - totalWagered },
                    { "GoodBetCount", goodBetCount }
                };

                return analytics;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error calculating analytics");
                return new Dictionary<string, object>();
            }
        }
    }
}

