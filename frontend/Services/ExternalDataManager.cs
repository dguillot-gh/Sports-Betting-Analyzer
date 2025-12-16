using SportsBettingAnalyzer.Data;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    /// <summary>
    /// Centralized service for managing all external data operations
/// Handles caching, provider selection, and data persistence
    /// </summary>
    public class ExternalDataManager
    {
        private readonly Dictionary<string, IExternalDataProvider> _providers;
        private readonly ApplicationDbContext _context;
        private readonly ILogger<ExternalDataManager> _logger;
    
      // Simple in-memory cache with expiration
        private readonly Dictionary<string, (object Data, DateTime Expiry)> _cache = new();
        private const int CacheExpiryMinutes = 30;

        public ExternalDataManager(
  ApplicationDbContext context,
 ILogger<ExternalDataManager> logger,
            ESPNDataProvider espnProvider,
          WebScrapingDataProvider scrapingProvider)
        {
     _context = context;
          _logger = logger;
            
            // Register all available providers
_providers = new Dictionary<string, IExternalDataProvider>
            {
            { "ESPN", espnProvider },
      { "WebScraping", scrapingProvider }
            };
        }

        /// <summary>
   /// Fetch historical games from the best available provider
        /// Falls back to database if external sources fail
        /// </summary>
        public async Task<List<HistoricalGameResult>> FetchHistoricalGamesAsync(
         string sport,
 DateTime? startDate = null,
            DateTime? endDate = null,
     string? preferredProvider = null)
     {
    try
            {
        _logger.LogInformation("=== ExternalDataManager.FetchHistoricalGamesAsync CALLED ===");
        _logger.LogInformation("Sport: {Sport}, StartDate: {StartDate}, EndDate: {EndDate}, PreferredProvider: {Provider}",
            sport, startDate, endDate, preferredProvider ?? "none");

              // Check cache first
         var cacheKey = $"historical_{sport}_{startDate:yyyyMMdd}_{endDate:yyyyMMdd}";
         if (TryGetFromCache(cacheKey, out var cachedGames))
    {
         _logger.LogInformation("Returning cached historical games for {Sport}", sport);
    return (List<HistoricalGameResult>)cachedGames!;
       }

 var games = new List<HistoricalGameResult>();

       // Try preferred provider first
        if (!string.IsNullOrEmpty(preferredProvider) && _providers.ContainsKey(preferredProvider))
       {
            _logger.LogInformation("Trying preferred provider: {Provider}", preferredProvider);
     games = await _providers[preferredProvider].GetHistoricalGamesAsync(sport, startDate, endDate);
            _logger.LogInformation("Preferred provider returned {Count} games", games.Count);
     }

                // Try other providers if preferred didn't return data
       if (games.Count == 0)
        {
            _logger.LogInformation("Trying all available providers...");
      foreach (var provider in _providers.Values)
           {
                _logger.LogInformation("Attempting provider: {Provider}", provider.ProviderName);
            games = await provider.GetHistoricalGamesAsync(sport, startDate, endDate);
                _logger.LogInformation("Provider {Provider} returned {Count} games", provider.ProviderName, games.Count);
   if (games.Count > 0)
              {
       _logger.LogInformation("Successfully fetched {Count} games from {Provider}", games.Count, provider.ProviderName);
         break;
                  }
       }
     }

                // Cache and persist the results
      if (games.Count > 0)
 {
        SetCache(cacheKey, games);
      await PersistGamesToDatabase(games);
     }
            else
                {
   _logger.LogWarning("No games fetched from any provider");
     }

  return games;
   }
    catch (Exception ex)
            {
          _logger.LogError(ex, "Error fetching historical games");
 // Fallback to database
             return await FallbackToDatabase(sport);
    }
        }

        /// <summary>
        /// Fetch live games and odds
   /// </summary>
        public async Task<List<LiveGameData>> FetchLiveGamesAsync(string sport, string? preferredProvider = null)
        {
          try
            {
                _logger.LogInformation("Fetching live games for {Sport}", sport);

              // Check cache (shorter expiry for live data)
         var cacheKey = $"live_{sport}";
       if (TryGetFromCache(cacheKey, out var cachedGames))
   {
             _logger.LogInformation("Returning cached live games for {Sport}", sport);
            return (List<LiveGameData>)cachedGames!;
            }

  var games = new List<LiveGameData>();

       if (!string.IsNullOrEmpty(preferredProvider) && _providers.ContainsKey(preferredProvider))
       {
     games = await _providers[preferredProvider].GetLiveGamesAsync(sport);
         }

                if (games.Count == 0)
      {
      foreach (var provider in _providers.Values)
    {
        games = await provider.GetLiveGamesAsync(sport);
         if (games.Count > 0)
        {
        _logger.LogInformation("Successfully fetched {Count} live games from {Provider}", games.Count, provider.ProviderName);
        break;
      }
          }
                }

           if (games.Count > 0)
           {
          SetCache(cacheKey, games, expiryMinutes: 5); // Shorter cache for live data
                }

       return games;
     }
       catch (Exception ex)
            {
     _logger.LogError(ex, "Error fetching live games");
        return new List<LiveGameData>();
    }
        }

        /// <summary>
        /// Fetch team statistics
     /// </summary>
        public async Task<TeamStats?> FetchTeamStatsAsync(string teamName, string sport, string? preferredProvider = null)
    {
        try
      {
      _logger.LogInformation("Fetching stats for {Team} in {Sport}", teamName, sport);

             var cacheKey = $"team_{teamName}_{sport}";
    if (TryGetFromCache(cacheKey, out var cachedStats))
      {
           return (TeamStats?)cachedStats;
  }

 TeamStats? stats = null;

            if (!string.IsNullOrEmpty(preferredProvider) && _providers.ContainsKey(preferredProvider))
          {
  stats = await _providers[preferredProvider].GetTeamStatsAsync(teamName, sport);
                }

      if (stats == null)
         {
          foreach (var provider in _providers.Values)
{
      stats = await provider.GetTeamStatsAsync(teamName, sport);
    if (stats != null)
  {
                break;
      }
   }
          }

     if (stats != null)
   {
          SetCache(cacheKey, stats);
             }

      return stats;
            }
         catch (Exception ex)
  {
        _logger.LogError(ex, "Error fetching team stats");
   return null;
            }
        }

        /// <summary>
  /// Validate all providers' connectivity
 /// </summary>
        public async Task<Dictionary<string, bool>> ValidateProvidersAsync()
     {
 var results = new Dictionary<string, bool>();

   foreach (var (name, provider) in _providers)
          {
      try
    {
  var isValid = await provider.ValidateConnectionAsync();
    results[name] = isValid;
        _logger.LogInformation("Provider {Name} validation: {Status}", name, isValid ? "Success" : "Failed");
             }
    catch (Exception ex)
   {
         _logger.LogError(ex, "Error validating provider {Name}", name);
         results[name] = false;
           }
            }

            return results;
        }

        // PRIVATE HELPER METHODS

        private async Task PersistGamesToDatabase(List<HistoricalGameResult> games)
        {
            try
     {
    foreach (var game in games)
    {
         var existingGame = _context.HistoricalGameResults
       .FirstOrDefault(g => g.GameDate == game.GameDate 
    && g.Team1 == game.Team1 
&& g.Team2 == game.Team2);

        if (existingGame == null)
     {
    _context.HistoricalGameResults.Add(game);
        }
    }

        await _context.SaveChangesAsync();
        _logger.LogInformation("Persisted {Count} games to database", games.Count);
          }
            catch (Exception ex)
      {
        _logger.LogError(ex, "Error persisting games to database");
            }
      }

   private async Task<List<HistoricalGameResult>> FallbackToDatabase(string sport)
        {
            try
            {
        _logger.LogInformation("Falling back to database for {Sport} games", sport);
             return _context.HistoricalGameResults
      .Where(g => g.Sport == sport)
           .OrderByDescending(g => g.GameDate)
            .Take(100)
          .ToList();
        }
       catch (Exception ex)
        {
    _logger.LogError(ex, "Error fetching from database");
      return new List<HistoricalGameResult>();
            }
        }

        private bool TryGetFromCache(string key, out object? data)
        {
            if (_cache.TryGetValue(key, out var cachedItem))
        {
       if (cachedItem.Expiry > DateTime.UtcNow)
    {
     data = cachedItem.Data;
         return true;
       }
  else
        {
           _cache.Remove(key);
         }
      }

            data = null;
   return false;
        }

        private void SetCache(string key, object data, int expiryMinutes = CacheExpiryMinutes)
        {
            _cache[key] = (data, DateTime.UtcNow.AddMinutes(expiryMinutes));
        }
    }
}
