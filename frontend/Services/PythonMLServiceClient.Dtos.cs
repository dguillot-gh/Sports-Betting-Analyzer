// PythonMLServiceClient.Dtos.cs — request/response DTOs for the ML service client (namespace unchanged).
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

public class AnalysisSaveRequest
{
    [JsonPropertyName("sport")]
    public string Sport { get; set; } = "";
    
    [JsonPropertyName("home_team")]
    public string HomeTeam { get; set; } = "";
    
    [JsonPropertyName("away_team")]
    public string AwayTeam { get; set; } = "";
    
    [JsonPropertyName("analysis")]
    public object Analysis { get; set; } = default!;
}

public class AnalysisCacheListResponse
{
    [JsonPropertyName("count")]
    public int Count { get; set; }
    
    [JsonPropertyName("analyses")]
    public List<CachedAnalysisEntry> Analyses { get; set; } = new();
}

public class CachedAnalysisEntry
{
    [JsonPropertyName("sport")]
    public string Sport { get; set; } = "";
    
    [JsonPropertyName("home_team")]
    public string HomeTeam { get; set; } = "";
    
    [JsonPropertyName("away_team")]
    public string AwayTeam { get; set; } = "";
    
    [JsonPropertyName("timestamp")]
    public string Timestamp { get; set; } = "";
    
    [JsonPropertyName("analysis")]
    public JsonElement Analysis { get; set; }
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

    [JsonPropertyName("last_updated")]
    public string? LastUpdated { get; set; }
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
    public string Message { get; set; } = string.Empty;

    [JsonPropertyName("files")]
    public List<string>? Files { get; set; }

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; set; }
}

public class DashboardTopPicksResponse
{
    [JsonPropertyName("date")]
    public string? Date { get; set; }

    [JsonPropertyName("sportsbook")]
    public string Sportsbook { get; set; } = "";

    [JsonPropertyName("count")]
    public int Count { get; set; }

    [JsonPropertyName("picks")]
    public List<DashboardTopPick> Picks { get; set; } = new();
}

public class DashboardTopPick
{
    [JsonPropertyName("sport")]
    public string Sport { get; set; } = "";

    [JsonPropertyName("home_team")]
    public string HomeTeam { get; set; } = "";

    [JsonPropertyName("away_team")]
    public string AwayTeam { get; set; } = "";

    [JsonPropertyName("game_time")]
    public string GameTime { get; set; } = "";

    [JsonPropertyName("winner")]
    public string Winner { get; set; } = "";

    [JsonPropertyName("probability")]
    public double Probability { get; set; }

    [JsonPropertyName("edge")]
    public double Edge { get; set; }

    [JsonPropertyName("value_score")]
    public double ValueScore { get; set; }
}

public class LeagueStandingsResponse
{
    [JsonPropertyName("sport")]
    public string Sport { get; set; } = "";

    [JsonPropertyName("season")]
    public int Season { get; set; }

    [JsonPropertyName("source")]
    public string? Source { get; set; }

    [JsonPropertyName("standings")]
    public List<LeagueStandingEntry> Standings { get; set; } = new();
}

public class LeagueStandingEntry
{
    [JsonPropertyName("team")]
    public string Team { get; set; } = "";

    [JsonPropertyName("wins")]
    public int Wins { get; set; }

    [JsonPropertyName("losses")]
    public int Losses { get; set; }

    [JsonPropertyName("ot_losses")]
    public int? OtLosses { get; set; }

    [JsonPropertyName("points")]
    public int? Points { get; set; }

    [JsonPropertyName("points_for")]
    public int PointsFor { get; set; }

    [JsonPropertyName("points_against")]
    public int PointsAgainst { get; set; }

    [JsonPropertyName("record")]
    public string? Record { get; set; }

    [JsonPropertyName("win_pct")]
    public double? WinPct { get; set; }
}

/// <summary>
/// Version information models
/// </summary>
public class VersionInfo
{
    [JsonPropertyName("version")]
    public string Version { get; set; } = string.Empty;

    [JsonPropertyName("git_sha")]
    public string GitSha { get; set; } = string.Empty;

    [JsonPropertyName("git_branch")]
    public string GitBranch { get; set; } = string.Empty;

    [JsonPropertyName("build_time")]
    public string BuildTime { get; set; } = string.Empty;

    [JsonPropertyName("environment")]
    public string Environment { get; set; } = string.Empty;

    [JsonPropertyName("deployment_id")]
    public string DeploymentId { get; set; } = string.Empty;

    [JsonPropertyName("components")]
    public List<DeploymentComponent> Components { get; set; } = new();
}

public class DeploymentComponent
{
    [JsonPropertyName("component_name")]
    public string ComponentName { get; set; } = string.Empty;

    [JsonPropertyName("component_version")]
    public string ComponentVersion { get; set; } = string.Empty;

    [JsonPropertyName("component_sha")]
    public string ComponentSha { get; set; } = string.Empty;

    [JsonPropertyName("status")]
    public string Status { get; set; } = string.Empty;
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

// ===== Missing Models =====

public class RdaImportStatus
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "unknown";

    [JsonPropertyName("started_at")]
    public string? StartedAt { get; set; }

    [JsonPropertyName("progress")]
    public List<string> Progress { get; set; } = new();

    [JsonPropertyName("error")]
    public string? Error { get; set; }
}

public class SportImportStatus
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "unknown";

    [JsonPropertyName("progress")]
    public List<string> Progress { get; set; } = new();

    [JsonPropertyName("error")]
    public string? Error { get; set; }
}

public class BaseballImportStatus
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "unknown";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("progress")]
    public List<string> Progress { get; set; } = new();

    [JsonPropertyName("error")]
    public string? Error { get; set; }
}

public class BaseballImportSummary
{
    [JsonPropertyName("teams_count")]
    public int TeamsCount { get; set; }
    
    [JsonPropertyName("last_updated")]
    public string? LastUpdated { get; set; }

    [JsonPropertyName("generated_at")]
    public string? GeneratedAt { get; set; }

    [JsonPropertyName("division")]
    public int Division { get; set; }

    [JsonPropertyName("imported_teams")]
    public int ImportedTeams { get; set; }
}

/// <summary>
/// Client for Python ML Service FastAPI
/// </summary>
