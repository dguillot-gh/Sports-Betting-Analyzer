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

namespace SportsBettingAnalyzer.Services;

/// <summary>
/// Configuration options for Python ML Service
/// </summary>
public class PythonMLOptions
{
    public string BaseUrl { get; set; } = "http://localhost:8000";
    public int TimeoutSeconds { get; set; } = 300;
    public int HealthCheckIntervalSeconds { get; set; } = 30;
}

/// <summary>
/// Response models from Python ML Service
/// </summary>
public class SchemaInfo
{
    [JsonPropertyName("features")]
    public Dictionary<string, List<string>>? Features { get; set; }

    [JsonPropertyName("targets")]
    public Dictionary<string, string>? Targets { get; set; }
}

public class DataSchema
{
    [JsonPropertyName("columns")]
    public List<string> Columns { get; set; } = new();

    [JsonPropertyName("rows")]
    public List<Dictionary<string, object>> Rows { get; set; } = new();

    [JsonPropertyName("total_rows")]
    public int TotalRows { get; set; }
}

public class TrainRequest
{
    [JsonPropertyName("task")]
    public string Task { get; set; } = "";

    [JsonPropertyName("test_start_season")]
    public int? TestStartSeason { get; set; }

    [JsonPropertyName("train_start_season")]
    public int? TrainStartSeason { get; set; }

    [JsonPropertyName("series")]
    public string? Series { get; set; }

    [JsonPropertyName("hyperparameters")]
    public Dictionary<string, object>? Hyperparameters { get; set; }
}

public class TrainResponse
{
    [JsonPropertyName("model_path")]
    public string ModelPath { get; set; } = "";

    [JsonPropertyName("metrics_path")]
    public string MetricsPath { get; set; } = "";

    [JsonPropertyName("metrics")]
    public System.Text.Json.JsonElement Metrics { get; set; }
    
    // Multi-target training support (NASCAR)
    [JsonPropertyName("multi_target")]
    public bool MultiTarget { get; set; } = false;
    
    [JsonPropertyName("targets_trained")]
    public List<string>? TargetsTrained { get; set; }
    
    [JsonPropertyName("results")]
    public Dictionary<string, TargetResult>? Results { get; set; }
}

public class TargetResult
{
    [JsonPropertyName("model_path")]
    public string ModelPath { get; set; } = "";
    
    [JsonPropertyName("metrics_path")]
    public string MetricsPath { get; set; } = "";
}

public class PredictRequest
{
    [JsonPropertyName("features")]
    public Dictionary<string, object>? Features { get; set; }
}
public class PredictResponse
{
    [JsonPropertyName("prediction")]
    public object? Prediction { get; set; }

    [JsonPropertyName("probability")]
    public double? Probability { get; set; }

    [JsonPropertyName("confidence")]
    public string? Confidence { get; set; }

    [JsonPropertyName("confidence_percent")]
    public int? ConfidencePercent { get; set; }

    [JsonPropertyName("series")]
    public string? Series { get; set; }
}

public class NcaabComparisonResponse
{
    [JsonPropertyName("home_team")]
    public string HomeTeam { get; set; } = "";

    [JsonPropertyName("away_team")]
    public string AwayTeam { get; set; } = "";

    [JsonPropertyName("models")]
    public Dictionary<string, JsonElement> Models { get; set; } = new();

    public NcaabInternalResult? GetSimpleResult() => GetResult<NcaabInternalResult>("simple");
    public NcaabInternalResult? GetXgbResult() => GetResult<NcaabInternalResult>("xgb");
    public NcaabEspnResult? GetEspnResult() => GetResult<NcaabEspnResult>("espn");

    private T? GetResult<T>(string key) where T : class
    {
        if (Models.TryGetValue(key, out var el))
        {
            return JsonSerializer.Deserialize<T>(el.GetRawText());
        }
        return null;
    }
}

public class NcaabInternalResult
{
    [JsonPropertyName("win_prob")]
    public double WinProb { get; set; }
    
    [JsonPropertyName("total")]
    public double Total { get; set; }
    
    [JsonPropertyName("winner")]
    public string Winner { get; set; } = "";
}

public class NcaabEspnResult
{
    [JsonPropertyName("win_prob")]
    public double WinProb { get; set; }
    
    [JsonPropertyName("total_over_prob")]
    public double TotalOverProb { get; set; }
    
    [JsonPropertyName("winner")]
    public string Winner { get; set; } = "";
}

public class NbaComparisonResponse
{
    [JsonPropertyName("home_team")]
    public string HomeTeam { get; set; } = "";

    [JsonPropertyName("away_team")]
    public string AwayTeam { get; set; } = "";

    [JsonPropertyName("models")]
    public Dictionary<string, object> Models { get; set; } = new();

    // Helper to get typed results
    public KyleskomEnsembleResult? GetKyleskomResult()
    {
        if (Models.TryGetValue("kyle", out var kyleObj) && kyleObj is JsonElement el)
        {
            return JsonSerializer.Deserialize<KyleskomEnsembleResult>(el.GetRawText());
        }
        return null;
    }
}

public class KyleskomEnsembleResult
{
    [JsonPropertyName("home_team")]
    public string? HomeTeam { get; set; }

    [JsonPropertyName("away_team")]
    public string? AwayTeam { get; set; }

    [JsonPropertyName("home_win_probability")]
    public double HomeWinProbability { get; set; }

    [JsonPropertyName("nn_home_win_probability")]
    public double? NnHomeWinProbability { get; set; }

    [JsonPropertyName("predicted_winner")]
    public string? PredictedWinner { get; set; }

    [JsonPropertyName("confidence")]
    public double Confidence { get; set; }

    [JsonPropertyName("ev_home")]
    public double? HomeEv { get; set; }

    [JsonPropertyName("ev_away")]
    public double? AwayEv { get; set; }

    [JsonPropertyName("kelly_home")]
    public double? HomeKelly { get; set; }

    [JsonPropertyName("kelly_away")]
    public double? AwayKelly { get; set; }
}

public class ModelInfo
{
    [JsonPropertyName("sport")]
    public string Sport { get; set; } = "";

    [JsonPropertyName("series")]
    public string Series { get; set; } = "";

    [JsonPropertyName("task")]
    public string Task { get; set; } = "";

    [JsonPropertyName("metrics")]
    public Dictionary<string, object>? Metrics { get; set; }

    [JsonPropertyName("last_updated")]
    public double LastUpdated { get; set; }
}

public class ProfileData
{
    [JsonPropertyName("stats")]
    public Dictionary<string, object> Stats { get; set; } = new();

    [JsonPropertyName("splits")]
    public Dictionary<string, Dictionary<string, object>> Splits { get; set; } = new();

    [JsonPropertyName("history")]
    public List<Dictionary<string, object>> History { get; set; } = new();

    [JsonPropertyName("years")]
    public List<int> Years { get; set; } = new();
}

public class UpcomingRaceInfo
{
    [JsonPropertyName("track")]
    public string Track { get; set; } = "";

    [JsonPropertyName("year")]
    public int Year { get; set; }

    [JsonPropertyName("race_name")]
    public string RaceName { get; set; } = "";

    [JsonPropertyName("drivers")]
    public List<string> Drivers { get; set; } = new();
}

public class SimulationRequest
{
    [JsonPropertyName("drivers")]
    public List<string> Drivers { get; set; } = new();

    [JsonPropertyName("year")]
    public int Year { get; set; }

    [JsonPropertyName("track_type")]
    public string TrackType { get; set; } = "Intermediate";

    [JsonPropertyName("num_simulations")]
    public int NumSimulations { get; set; } = 1000;
}

public class SimulationResponse
{
    [JsonPropertyName("metadata")]
    public SimulationMetadata Metadata { get; set; } = new();

    [JsonPropertyName("results")]
    public List<SimulationDriverResult> Results { get; set; } = new();
}

public class SimulationMetadata
{
    [JsonPropertyName("year")]
    public int Year { get; set; }

    [JsonPropertyName("track_type")]
    public string TrackType { get; set; } = "";

    [JsonPropertyName("simulations")]
    public int Simulations { get; set; }

    [JsonPropertyName("driver_count")]
    public int DriverCount { get; set; }
}

public class SimulationDriverResult
{
    [JsonPropertyName("driver")]
    public string Driver { get; set; } = "";

    [JsonPropertyName("avg_finish")]
    public double AvgFinish { get; set; }

    [JsonPropertyName("win_prob")]
    public double WinProb { get; set; }

    [JsonPropertyName("top_5_prob")]
    public double Top5Prob { get; set; }

    [JsonPropertyName("top_10_prob")]
    public double Top10Prob { get; set; }

    [JsonPropertyName("best_finish")]
    public int BestFinish { get; set; }

    [JsonPropertyName("worst_finish")]
    public int WorstFinish { get; set; }
}

// Data Management Models
public class DataStatusResponse
{
    [JsonPropertyName("nascar")]
    public SportDataStatus? Nascar { get; set; }

    [JsonPropertyName("nfl")]
    public SportDataStatus? Nfl { get; set; }

    [JsonPropertyName("nba")]
    public SportDataStatus? Nba { get; set; }
}

public class SportDataStatus
{
    [JsonPropertyName("source")]
    public string Source { get; set; } = "";

    [JsonPropertyName("source_url")]
    public string? SourceUrl { get; set; }

    [JsonPropertyName("dataset")]
    public string? Dataset { get; set; }

    [JsonPropertyName("files")]
    public System.Text.Json.JsonElement? Files { get; set; }

    [JsonPropertyName("last_commit")]
    public string? LastCommit { get; set; }

    [JsonPropertyName("commit_message")]
    public string? CommitMessage { get; set; }

    [JsonPropertyName("models")]
    public int Models { get; set; }

    [JsonPropertyName("model_accuracy")]
    public double? ModelAccuracy { get; set; }

    [JsonPropertyName("datasets")]
    public List<DatasetConfig>? Datasets { get; set; }
}

public class DatasetConfig
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("type")]
    public string Type { get; set; } = "kaggle";

    [JsonPropertyName("added_at")]
    public string? AddedAt { get; set; }

    [JsonPropertyName("last_updated")]
    public string? LastUpdated { get; set; }
}

public class DataUpdateResponse
{
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("files")]
    public List<string>? Files { get; set; }

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; set; }
}

public class RetrainResponse
{
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    [JsonPropertyName("sport")]
    public string Sport { get; set; } = "";

    [JsonPropertyName("task")]
    public string Task { get; set; } = "";

    [JsonPropertyName("metrics")]
    public Dictionary<string, object>? Metrics { get; set; }
}

/// <summary>
/// Client for Python ML Service FastAPI
/// </summary>
public class PythonMLServiceClient
{
    private readonly HttpClient _httpClient;
    public HttpClient HttpClient => _httpClient;
    private readonly ILogger<PythonMLServiceClient> _logger;
    private readonly PythonMLOptions _options;
    private bool _isHealthy = false;
    private DateTime _lastHealthCheck = DateTime.MinValue;

    public PythonMLServiceClient(
        HttpClient httpClient,
        IOptions<PythonMLOptions> options,
        ILogger<PythonMLServiceClient> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
        _options = options.Value;

        _httpClient.BaseAddress = new Uri(_options.BaseUrl);
        _httpClient.Timeout = TimeSpan.FromSeconds(_options.TimeoutSeconds);
    }

    /// <summary>
    /// Check if Python ML Service is available
    /// </summary>
    public async Task<bool> IsHealthyAsync()
    {
        var now = DateTime.UtcNow;

        // Cache health check for the configured interval
        if ((now - _lastHealthCheck).TotalSeconds < _options.HealthCheckIntervalSeconds && _lastHealthCheck != DateTime.MinValue)
        {
            return _isHealthy;
        }

        try
        {
            var response = await _httpClient.GetAsync("/health");
            _isHealthy = response.IsSuccessStatusCode;
            _lastHealthCheck = now;

            if (_isHealthy)
            {
                _logger.LogInformation("Python ML Service is healthy");
            }
            else
            {
                _logger.LogWarning("Python ML Service returned unhealthy status: {StatusCode}", response.StatusCode);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error checking Python ML Service health");
            _isHealthy = false;
            _lastHealthCheck = now;
        }

        return _isHealthy;
    }

    /// <summary>
    /// Get list of teams for a sport
    /// </summary>
    public async Task<List<Dictionary<string, object>>> GetTeamsAsync(string sport)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                // Return empty list instead of throwing to avoid crashing UI on offline service
                _logger.LogWarning("Python ML Service unavailable, returning empty team list");
                return new List<Dictionary<string, object>>();
            }
            return await _httpClient.GetFromJsonAsync<List<Dictionary<string, object>>>($"/{sport}/teams") 
                   ?? new List<Dictionary<string, object>>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting teams for sport: {Sport}", sport);
            return new List<Dictionary<string, object>>();
        }
    }

    /// <summary>
    /// Get feature and target schema for a sport
    /// </summary>
    public async Task<SchemaInfo> GetSchemaAsync(string sport)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }
            var response = await _httpClient.GetFromJsonAsync<SchemaInfo>($"/{sport}/schema");
            return response ?? throw new InvalidOperationException($"No schema found for sport: {sport}");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting schema for sport: {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get available data for a sport
    /// </summary>
    public async Task<DataSchema> GetDataAsync(string sport, int limit = 1000, int skip = 0, int? seasonMin = null, int? seasonMax = null, string? series = null, string? driver = null, string? trackType = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/data?limit={limit}&skip={skip}";
            if (seasonMin.HasValue)
                url += $"&season_min={seasonMin}";
            if (seasonMax.HasValue)
                url += $"&season_max={seasonMax}";
            if (!string.IsNullOrEmpty(series))
                url += $"&series={series}";
            if (!string.IsNullOrEmpty(driver))
                url += $"&driver={Uri.EscapeDataString(driver)}";
            if (!string.IsNullOrEmpty(trackType))
                url += $"&track_type={Uri.EscapeDataString(trackType)}";

            var response = await _httpClient.GetFromJsonAsync<DataSchema>(url);
            return response ?? new DataSchema { Columns = new(), Rows = new() };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting data for sport: {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Train a new model
    /// </summary>
    public async Task<TrainResponse> TrainAsync(string sport, string task, int? testStartSeason = null, int? trainStartSeason = null, Dictionary<string, object> hyperparameters = null, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var payload = new TrainRequest
            {
                Task = task,
                TestStartSeason = testStartSeason,
                TrainStartSeason = trainStartSeason,
                Hyperparameters = hyperparameters,
                Series = series
            };

            var url = $"/{sport}/train/{task}";
            var response = await _httpClient.PostAsJsonAsync(url, payload);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<TrainResponse>()
                ?? throw new InvalidOperationException("Failed to deserialize training response");

            _logger.LogInformation("Successfully trained {Sport} {Task} model. Metrics: {@Metrics}",
                sport, task, result.Metrics);

            return result;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error training {Sport} {Task} model", sport, task);
            throw;
        }
    }

    /// <summary>
    /// Trigger retraining of the NCAAB model
    /// </summary>
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

    /// <summary>
    /// Run NCAAB Backtest
    /// </summary>
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

    /// <summary>
    /// Make a prediction using a trained model
    /// </summary>
    public async Task<PredictResponse> PredictAsync(string sport, string task, PredictRequest request, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/predict/{task}";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            var response = await _httpClient.PostAsJsonAsync(url, request);
            response.EnsureSuccessStatusCode();

            return await response.Content.ReadFromJsonAsync<PredictResponse>()
                ?? new PredictResponse();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error predicting for {Sport} {Task}", sport, task);
            throw;
        }
    }

    /// <summary>
    /// Make batch predictions from a CSV file
    /// </summary>
    public async Task<List<Dictionary<string, object>>> PredictBatchAsync(string sport, string task, Stream fileStream, string fileName, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/predict/batch/{task}";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            using var content = new MultipartFormDataContent();
            using var streamContent = new StreamContent(fileStream);
            content.Add(streamContent, "file", fileName);

            var response = await _httpClient.PostAsync(url, content);
            response.EnsureSuccessStatusCode();

            return await response.Content.ReadFromJsonAsync<List<Dictionary<string, object>>>() 
                ?? new List<Dictionary<string, object>>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error running batch prediction for {Sport} {Task}", sport, task);
            throw;
        }
    }

    public async Task<Dictionary<string, Dictionary<string, object>>> GetDriverMappingsAsync(string sport, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/mappings/drivers";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            var response = await _httpClient.GetFromJsonAsync<Dictionary<string, Dictionary<string, object>>>(url);
            return response ?? new Dictionary<string, Dictionary<string, object>>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting driver mappings for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get list of available sports
    /// </summary>
    public Task<List<string>> GetAvailableSportsAsync()
    {
        return Task.FromResult(new List<string> { "nascar", "nfl" });
    }

    /// <summary>
    /// Get available series for NASCAR
    /// </summary>
    public Task<List<string>> GetNASCARSeriesAsync()
    {
        var series = new List<string> { "cup", "truck", "xfinity" };
        return Task.FromResult(series);
    }

    /// <summary>
    /// Trigger data enhancement process
    /// </summary>
    /// <remarks>NOTE: There's also an overload with optional series parameter at the bottom of this file</remarks>
    /* Replaced by EnhanceDataAsync with EnhanceResponse at line 932
    public async Task<Dictionary<string, object>> EnhanceDataAsync(string sport)
    {
        // Old implementation - removed
    }
    */

    /// <summary>
    /// Get list of trained models and their metrics
    /// </summary>
    public async Task<List<ModelInfo>> GetModelsAsync(string sport)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var response = await _httpClient.GetFromJsonAsync<List<ModelInfo>>($"/{sport}/models");
            return response ?? new List<ModelInfo>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting models for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Delete a trained model
    /// </summary>
    public async Task DeleteModelAsync(string sport, string series, string task)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var response = await _httpClient.DeleteAsync($"/{sport}/models/{series}/{task}");
            response.EnsureSuccessStatusCode();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error deleting {Sport} {Task} model", sport, task);
            throw;
        }
    }

    /// <summary>
    /// Get unique values for categorical features
    /// </summary>
    public async Task<Dictionary<string, List<object>>> GetFeatureValuesAsync(string sport, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/features/values";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            var response = await _httpClient.GetFromJsonAsync<Dictionary<string, List<object>>>(url);
            return response ?? new Dictionary<string, List<object>>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting feature values for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get list of available entities (drivers/teams)
    /// </summary>
    public async Task<List<string>> GetEntitiesAsync(string sport, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/entities";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            var response = await _httpClient.GetFromJsonAsync<List<string>>(url);
            return response ?? new List<string>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting entities for {Sport}", sport);
            throw;
        }
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/entities";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            var response = await _httpClient.GetFromJsonAsync<List<string>>(url);
            return response ?? new List<string>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting entities for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get list of available teams
    /// </summary>
    public async Task<List<string>> GetTeamsAsync(string sport, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/teams";
            if (!string.IsNullOrEmpty(series))
                url += $"?series={series}";

            var response = await _httpClient.GetFromJsonAsync<List<string>>(url);
            return response ?? new List<string>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting teams for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get list of drivers, optionally filtered by team
    /// </summary>
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

    /// <summary>
    /// Get driver roster for a specific series with metadata (team, manufacturer, race counts)
    /// </summary>
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

    /// <summary>
    /// Get comprehensive stats for a specific entity
    /// </summary>
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

    /// <summary>
    /// Get upcoming race info
    /// </summary>
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

    /// <summary>
    /// Check for updates for all configured datasets
    /// </summary>
    public async Task<Dictionary<string, Dictionary<string, object>>> CheckUpdatesAsync(string sport)
    {
        try
        {
            var response = await _httpClient.PostAsync($"/data/check-updates/{sport}", null);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadFromJsonAsync<Dictionary<string, Dictionary<string, object>>>()
                ?? new Dictionary<string, Dictionary<string, object>>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error checking updates for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get update history/changelog
    /// </summary>
    public async Task<List<Dictionary<string, object>>> GetHistoryAsync(string sport)
    {
        try
        {
            var response = await _httpClient.GetFromJsonAsync<List<Dictionary<string, object>>>($"/data/history/{sport}");
            return response ?? new List<Dictionary<string, object>>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting history for {Sport}", sport);
            return new List<Dictionary<string, object>>();
        }
    }

    /// <summary>
    /// Add a new dataset configuration
    /// </summary>
    public async Task<bool> AddDatasetAsync(string sport, string datasetId, string type = "kaggle")
    {
        try
        {
            var payload = new { dataset_id = datasetId, type = type };
            var response = await _httpClient.PostAsJsonAsync($"/data/datasets/{sport}", payload);
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error adding dataset {DatasetId} to {Sport}", datasetId, sport);
            throw;
        }
    }

    /// <summary>
    /// Remove a dataset configuration
    /// </summary>
    public async Task<bool> RemoveDatasetAsync(string sport, string datasetId)
    {
        try
        {
            // Encode datasetId because it contains slashes (e.g. owner/dataset)
            // But FastAPI path param handles it if configured correctly, or we pass it safely.
            // Using a simple slash encoding might be tricky if the API expects path param.
            // The API is: DELETE /data/datasets/{sport}/{dataset_id:path}
            // So we can just append it, but URI encoding helps safely transmit special chars.
            // However, FastAPI ":path" expects the slashes to be part of the path structure potentially.
            // Let's rely on standard URL rules. 
            // In request, we usually do NOT encode the slash that separates path segments, 
            // but here "owner/dataset" IS the ID.
            // Is it treated as one segment or two? 
            // FastAPI with `{dataset_id:path}` accepts arbitrary slashes.
            // So `owner/dataset` works.
            
            var response = await _httpClient.DeleteAsync($"/data/datasets/{sport}/{datasetId}");
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error removing dataset {DatasetId} from {Sport}", datasetId, sport);
            throw;
        }
    }

    /// <summary>
    /// Run Monte Carlo simulation
    /// </summary>
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

            return await response.Content.ReadFromJsonAsync<SimulationResponse>()
                ?? new SimulationResponse();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error running simulation for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get data status for all sports
    /// </summary>
    public async Task<DataStatusResponse?> GetDataStatusAsync()
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                return null;
            }

            return await _httpClient.GetFromJsonAsync<DataStatusResponse>("/data/status");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting data status");
            return null;
        }
    }

    /// <summary>
    /// Update data for a sport from external source
    /// </summary>
    public async Task<DataUpdateResponse> UpdateDataAsync(string sport, string? dataset = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/data/update/{sport}";
            if (!string.IsNullOrEmpty(dataset))
            {
                url += $"?dataset={Uri.EscapeDataString(dataset)}";
            }

            var response = await _httpClient.PostAsync(url, null);
            response.EnsureSuccessStatusCode();

            return await response.Content.ReadFromJsonAsync<DataUpdateResponse>()
                ?? new DataUpdateResponse { Success = false, Message = "No response" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error updating data for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Retrain model for a sport
    /// </summary>
    public async Task<RetrainResponse> RetrainModelAsync(string sport, string task = "classification", string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var request = new { task, series };
            var response = await _httpClient.PostAsJsonAsync($"/data/retrain/{sport}", request);
            response.EnsureSuccessStatusCode();

            return await response.Content.ReadFromJsonAsync<RetrainResponse>()
                ?? new RetrainResponse { Success = false };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error retraining model for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Enhance data for a sport (adds computed features)
    /// </summary>
    public async Task<EnhanceResponse> EnhanceDataAsync(string sport, string? series = null)
    {
        try
        {
            if (!await IsHealthyAsync())
            {
                throw new InvalidOperationException("Python ML Service is not available");
            }

            var url = $"/{sport}/enhance";
            if (!string.IsNullOrEmpty(series))
            {
                url += $"?series={series}";
            }
            
            var response = await _httpClient.PostAsync(url, null);
            response.EnsureSuccessStatusCode();

            return await response.Content.ReadFromJsonAsync<EnhanceResponse>()
                ?? new EnhanceResponse { Success = false };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error enhancing data for {Sport}", sport);
            throw;
        }
    }

    /// <summary>
    /// Get AI Analysis (Multi-Engine + LLM)
    /// </summary>
    public async Task<AiAnalysisResult?> AnalyzeMatchupAsync(string sport, string homeTeam, string awayTeam, string homeStats = "{}", string awayStats = "{}")
    {
        try
        {
            if (!await IsHealthyAsync())
                return null;

            var url = $"/ai/analyze?sport={sport}&home_team={Uri.EscapeDataString(homeTeam)}&away_team={Uri.EscapeDataString(awayTeam)}&home_stats={Uri.EscapeDataString(homeStats)}&away_stats={Uri.EscapeDataString(awayStats)}";
            var response = await _httpClient.PostAsync(url, null);
            
            if (!response.IsSuccessStatusCode) return null;
            
            return await response.Content.ReadFromJsonAsync<AiAnalysisResult>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting AI analysis for {Home} vs {Away}", homeTeam, awayTeam);
            return null;
        }
    }

    /// <summary>
    /// Get ESPN Predictions (FPI/BPI)
    /// </summary>
    public async Task<EspnResponse?> GetEspnPredictionsAsync(string sport)
    {
        try
        {
             if (!await IsHealthyAsync())
                return null;
                
             var url = $"/espn/{sport}/predictions";
             return await _httpClient.GetFromJsonAsync<EspnResponse>(url);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting ESPN predictions for {Sport}", sport);
            return null;
        }
    }

    /// <summary>
    /// Get NBA model comparison (Simple, Kyle, Apex)
    /// </summary>
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

    /// <summary>
    /// Get NASCAR live race predictions and odds
    /// </summary>
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

    /// <summary>
    /// Trigger NASCAR Model Retraining
    /// </summary>
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

    /// <summary>
    /// Get NCAAB Team Hit Rates
    /// </summary>
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

    /// <summary>
    /// Get NCAAB model comparison (Simple, XGBoost v2, ESPN BPI)
    /// </summary>
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

public class AiAnalysisResult
{
    [JsonPropertyName("sport")]
    public string Sport { get; set; } = "";
    
    [JsonPropertyName("matchup")]
    public string Matchup { get; set; } = "";
    
    [JsonPropertyName("engines")]
    public Dictionary<string, object> Engines { get; set; } = new();
    
    [JsonPropertyName("llm_insight")]
    public AiInsight? LlmInsight { get; set; }
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