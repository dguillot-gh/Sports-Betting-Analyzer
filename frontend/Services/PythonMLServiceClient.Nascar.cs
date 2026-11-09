// PythonMLServiceClient.Nascar.cs — part of PythonMLServiceClient (split for readability; public API unchanged).
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

// Nascar-specific ML service methods
public partial class PythonMLServiceClient
{

    public Task<List<string>> GetNASCARSeriesAsync()
    {
        var series = new List<string> { "cup", "truck", "xfinity" };
        return Task.FromResult(series);
    }

    public async Task<List<string>> GetDriversAsync(string sport, string? series = null, string? team = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/drivers";
            var queryParams = new List<string>();
            
            if (!string.IsNullOrEmpty(series))
                queryParams.Add($"series={series}");
                
            if (!string.IsNullOrEmpty(team))
                queryParams.Add($"team={Uri.EscapeDataString(team)}");
                
            if (queryParams.Count > 0)
                url += "?" + string.Join("&", queryParams);

            var response = await _httpClient.GetFromJsonAsync<List<string>>(url);
            return response ?? new List<string>();
        }
        catch (Exception)
        {
            throw;
        }
    }

    public async Task<List<DriverRoster>> GetRosterAsync(string sport, string series, int minRaces = 1, int? year = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/roster/{series}?min_races={minRaces}";
            if (year.HasValue)
            {
                url += $"&year={year.Value}";
            }
            var response = await _httpClient.GetFromJsonAsync<List<DriverRoster>>(url);
            return response ?? new List<DriverRoster>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting roster for {Sport}/{Series} with min_races={MinRaces}", sport, series, minRaces);
            throw;
        }
    }

    public async Task<ProfileData> GetEntityProfileAsync(string sport, string entityId, string? series = null, int? year = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/profile/{Uri.EscapeDataString(entityId)}";
            var queryParams = new List<string>();
            
            if (!string.IsNullOrEmpty(series))
                queryParams.Add($"series={series}");
            
            if (year.HasValue)
                queryParams.Add($"year={year.Value}");
                
            if (queryParams.Count > 0)
                url += "?" + string.Join("&", queryParams);

            var response = await _httpClient.GetFromJsonAsync<ProfileData>(url);
            return response ?? new ProfileData();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting profile for {Sport} {EntityId}", sport, entityId);
            throw;
        }
    }

    public async Task<UpcomingRaceInfo?> GetUpcomingRaceAsync(string sport)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var response = await _httpClient.GetFromJsonAsync<UpcomingRaceInfo>($"/{sport}/upcoming");
            return response;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting upcoming race for {Sport}", sport);
            return null;
        }
    }

    public async Task<SimulationResponse> SimulateRaceAsync(string sport, SimulationRequest request, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/simulate";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            var response = await _httpClient.PostAsJsonAsync(url, request);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<SimulationResponse>()
                ?? new SimulationResponse();
            
            // Map Metadata if missing
            if (result.Metadata == null)
            {
                result.Metadata = new SimulationMetadata
                {
                    Year = request.Year,
                    TrackType = request.TrackType,
                    Simulations = request.NumSimulations,
                    DriverCount = result.Results?.Count ?? 0
                };
            }
            
            return result;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error running simulation for {Sport}", sport);
            throw;
        }
    }

    public async Task<NascarRacePredictions?> GetRacePredictionsAsync(int raceId)
    {
        try
        {
            var url = $"/nascar/predictions/{raceId}";
            return await _httpClient.GetFromJsonAsync<NascarRacePredictions>(url);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting NASCAR predictions for race {RaceId}", raceId);
            return null;
        }
    }

    public async Task<bool> TrainNascarModelAsync()
    {
        try
        {
            var response = await _httpClient.PostAsync("/nascar/train", null);
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error triggering NASCAR training");
            return false;
        }
    }
}
