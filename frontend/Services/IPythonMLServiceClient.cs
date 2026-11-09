// IPythonMLServiceClient.cs — DI contract for the Python ML service client.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services;

/// <summary>
/// Contract for talking to the Python ML service. Implementations must expose
/// the exact public method surface declared here (see
/// <c>IPythonMLServiceClientConformanceTests</c>, which cross-checks this file
/// against the partial implementation files).
/// </summary>
public interface IPythonMLServiceClient
{
    // Core
    Task<bool> IsHealthyAsync();
    Task<List<Dictionary<string, object>>> GetTeamsAsync(string sport);
    Task<SchemaInfo> GetSchemaAsync(string sport);
    Task<DataSchema> GetDataAsync(string sport, int limit = 1000, int skip = 0, int? seasonMin = null, int? seasonMax = null, string? series = null, string? driver = null, string? trackType = null);
    Task<TrainResponse> TrainAsync(string sport, string task, int? testStartSeason = null, int? trainStartSeason = null, Dictionary<string, object>? hyperparameters = null, string? series = null);
    Task<PredictResponse> PredictAsync(string sport, string task, PredictRequest request, string? series = null);
    Task<List<Dictionary<string, object>>> PredictBatchAsync(string sport, string task, Stream fileStream, string fileName, string? series = null);
    Task<Dictionary<string, Dictionary<string, object>>> GetDriverMappingsAsync(string sport, string? series = null);
    Task<List<string>> GetAvailableSportsAsync();
    Task<List<ModelInfo>> GetModelsAsync(string sport);
    Task DeleteModelAsync(string sport, string series, string task);
    Task<Dictionary<string, List<object>>> GetFeatureValuesAsync(string sport, string? series = null);
    Task<List<string>> GetEntitiesAsync(string sport, string? series = null);
    Task<List<string>> GetTeamsAsync(string sport, string? series = null);
    Task<Dictionary<string, Dictionary<string, object>>> CheckUpdatesAsync(string sport);
    Task<List<Dictionary<string, object>>> GetHistoryAsync(string sport);
    Task<bool> AddDatasetAsync(string sport, string datasetId, string type = "kaggle");
    Task<bool> RemoveDatasetAsync(string sport, string datasetId);
    Task<DataStatusResponse?> GetDataStatusAsync();
    Task<DataUpdateResponse> UpdateDataAsync(string sport, string? dataset = null);
    Task<RetrainResponse> RetrainModelAsync(string sport, string task = "classification", string? series = null);
    Task<EnhanceResponse> EnhanceDataAsync(string sport, string? series = null);
    Task<AiAnalysisReport?> AnalyzeMatchupAsync(string sport, string homeTeam, string awayTeam, string homeStats = "{}", string awayStats = "{}");
    Task<EspnResponse?> GetEspnPredictionsAsync(string sport);
    Task<AiQuota?> GetAiQuotaAsync();
    Task<AiAnalysisReport?> GetAiAnalysisAsync(string sport, string homeTeam, string awayTeam, string homeStats = "{}", string awayStats = "{}");
    Task<List<DashboardModelSummary>> GetModelSummaryAsync();
    Task<List<DashboardTopPick>> GetDashboardTopPicksAsync(int limit = 8, string sportsbook = "fanduel");
    Task<LeagueStandingsResponse?> GetLeagueStandingsAsync(string sport);
    Task<List<ImportLog>> GetImportLogsAsync(int limit = 50);
    Task<SchedulerStatus?> GetSchedulerStatusAsync();
    Task<bool> RunImportsAsync();
    Task<bool> SaveAnalysisAsync(string sport, string home, string away, object analysis);
    Task<AnalysisCacheListResponse> GetTodaysAnalysesAsync();
    Task<BaseballImportStatus?> GetBaseballImportStatusAsync();
    Task<DataUpdateResponse> ImportBaseballDataAsync(double year, string division, string source);
    Task<BaseballImportSummary?> GetBaseballImportSummaryAsync();
    Task<SportImportStatus?> GetImportStatusAsync(string sport);
    Task<DataUpdateResponse> ImportSportDataAsync(string sport, bool clearExisting);
    Task<VersionInfo> GetVersionInfoAsync();
    Task<List<DeploymentEntry>> GetDeploymentHistoryAsync(int limit = 10);
    Task<DataUpdateResponse> CreateReleaseAsync(int major, int minor = 0);

    // NASCAR
    Task<List<string>> GetNASCARSeriesAsync();
    Task<List<string>> GetDriversAsync(string sport, string? series = null, string? team = null);
    Task<List<DriverRoster>> GetRosterAsync(string sport, string series, int minRaces = 1, int? year = null);
    Task<ProfileData> GetEntityProfileAsync(string sport, string entityId, string? series = null, int? year = null);
    Task<UpcomingRaceInfo?> GetUpcomingRaceAsync(string sport);
    Task<SimulationResponse> SimulateRaceAsync(string sport, SimulationRequest request, string? series = null);
    Task<NascarRacePredictions?> GetRacePredictionsAsync(int raceId);
    Task<bool> TrainNascarModelAsync();

    // NBA
    Task<NbaComparisonResponse?> CompareNbaModelsAsync(string homeTeam, string awayTeam, double? totalLine = null, int? homeMl = null, int? awayMl = null);

    // NCAAB
    Task TrainNcaabModelAsync();
    Task<BacktestReport?> BacktestNcaabAsync();
    Task<HitRateResult?> GetNcaabHitRatesAsync(string team, string metric, double line, int lastN = 10);
    Task<NcaabComparisonResponse?> CompareNcaabModelsAsync(string homeTeam, string awayTeam, double? totalLine = null, int? homeMl = null, int? awayMl = null);
    Task<bool> UpdateTorvikDataAsync();
    Task<DataUpdateResponse> ImportNcaabDataAsync(int year, bool clearExisting);

    // NFL
    Task<JsonElement?> PredictNflBatchAsync(object request);
}
