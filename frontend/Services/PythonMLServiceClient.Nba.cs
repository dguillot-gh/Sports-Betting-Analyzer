// PythonMLServiceClient.Nba.cs — part of PythonMLServiceClient (split for readability; public API unchanged).
using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using SportsBettingAnalyzer.Models;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Services;

// Nba-specific ML service methods
public partial class PythonMLServiceClient
{

    public async Task<NbaComparisonResponse?> CompareNbaModelsAsync(string homeTeam, string awayTeam, double? totalLine = null, int? homeMl = null, int? awayMl = null)
    {
        try
        {
            var url = $"/apex/compare/nba?home_team={Uri.EscapeDataString(homeTeam)}&away_team={Uri.EscapeDataString(awayTeam)}";
            if (totalLine.HasValue) url += $"&total_line={totalLine.Value}";
            if (homeMl.HasValue) url += $"&home_ml={homeMl.Value}";
            if (awayMl.HasValue) url += $"&away_ml={awayMl.Value}";

            var response = await _httpClient.GetFromJsonAsync<NbaComparisonResponse>(url);
            return response;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting NBA model comparison for {Home} vs {Away}", homeTeam, awayTeam);
            return null;
        }
    }
}
