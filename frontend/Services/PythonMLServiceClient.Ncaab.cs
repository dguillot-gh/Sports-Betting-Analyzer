// PythonMLServiceClient.Ncaab.cs — part of PythonMLServiceClient (split for readability; public API unchanged).
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

// Ncaab-specific ML service methods
public partial class PythonMLServiceClient
{

    public async Task TrainNcaabModelAsync()
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var response = await _httpClient.PostAsync("/trends/ncaab/train", null);
            response.EnsureSuccessStatusCode();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error training NCAAB model");
            throw;
        }
    }

    public async Task<BacktestReport?> BacktestNcaabAsync()
    {
        try
        {
            if (!await IsHealthyAsync())
                return null;
                
            var response = await _httpClient.PostAsync("/trends/ncaab/backtest", null);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadFromJsonAsync<BacktestReport>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error running NCAAB backtest");
            return null;
        }
    }

    public async Task<HitRateResult?> GetNcaabHitRatesAsync(string team, string metric, double line, int lastN = 10)
    {
        try
        {
            var url = $"/trends/ncaab/hit-rate?team={Uri.EscapeDataString(team)}&metric={metric}&line={line}&last_n={lastN}";
            return await _httpClient.GetFromJsonAsync<HitRateResult>(url);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting hit rates for {Team}", team);
            return null;
        }
    }

    public async Task<NcaabComparisonResponse?> CompareNcaabModelsAsync(string homeTeam, string awayTeam, double? totalLine = null, int? homeMl = null, int? awayMl = null)
    {
        try
        {
            if (!await IsHealthyAsync())
                return null;

            var url = $"/apex/compare/ncaab?home_team={Uri.EscapeDataString(homeTeam)}&away_team={Uri.EscapeDataString(awayTeam)}";
            if (totalLine.HasValue) url += $"&total_line={totalLine.Value}";
            if (homeMl.HasValue) url += $"&home_ml={homeMl.Value}";
            if (awayMl.HasValue) url += $"&away_ml={awayMl.Value}";

            return await _httpClient.GetFromJsonAsync<NcaabComparisonResponse>(url);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting NCAAB model comparison for {Home} vs {Away}", homeTeam, awayTeam);
            return null;
        }
    }

    public async Task<bool> UpdateTorvikDataAsync()
    {
        try
        {
            var response = await _httpClient.PostAsync("/odds/ncaab/update-torvik", null);
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error triggering Torvik data update");
            return false;
        }
    }

    public async Task<DataUpdateResponse> ImportNcaabDataAsync(int year, bool clearExisting)
    {
         try
        {
            if (!await IsHealthyAsync()) throw new InvalidOperationException("Service unavailable");
            
            // Assuming this maps to a generic sport import or a specific ncaab endpoint
            // For now, mapping to the generic update/import for "ncaab"
            // You might need to adjust the URL if there's a specific endpoint for year/clear
            var url = $"/data/update/ncaab?year={year}&clear={clearExisting}";
            var response = await _httpClient.PostAsync(url, null);
            
            if (response.IsSuccessStatusCode)
            {
                return new DataUpdateResponse { Success = true, Message = "NCAAB Import started" };
            }
            return new DataUpdateResponse { Success = false, Message = "Failed to start import" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error triggering NCAAB import");
            return new DataUpdateResponse { Success = false, Message = ex.Message };
        }
    }
}
