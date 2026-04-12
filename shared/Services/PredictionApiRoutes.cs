using System;

namespace SportsBettingAnalyzer.Shared.Services;

public static class PredictionApiRoutes
{
    private static string WithSportsbook(string path, string sportsbook)
        => $"{ApiUrlHelper.NormalizeRoute(path)}?sportsbook={Uri.EscapeDataString(sportsbook)}";

    public static string NbaAnalyzeCached(string sportsbook = "fanduel")
        => $"{WithSportsbook("odds/nba/analyze-cached", sportsbook)}&include_cached=true";

    public static string NflPredictions(string sportsbook = "fanduel")
        => WithSportsbook("model-testing/nfl/predictions", sportsbook);

    public static string NhlAnalyzeAll(string sportsbook = "fanduel")
        => WithSportsbook("nhl/analyze-all", sportsbook);

    public static string NcaabAnalyzeAll(string sportsbook = "fanduel")
        => WithSportsbook("odds/ncaab/analyze-all", sportsbook);

    public static string CfbAnalyzeAll(string sportsbook = "fanduel")
        => WithSportsbook("odds/cfb/analyze-all", sportsbook);

    public static string CollegeBaseballAnalyzeAll(string sportsbook = "fanduel")
        => WithSportsbook("odds/college-baseball/analyze-all", sportsbook);

    public static string MlbAnalyzeAll(string sportsbook = "fanduel")
        => WithSportsbook("odds/mlb/analyze-all", sportsbook);

    public static string MlbTeamStats()
        => ApiUrlHelper.NormalizeRoute("odds/mlb/team-stats");

    public static string MlbModelMetrics()
        => ApiUrlHelper.NormalizeRoute("odds/mlb/model-metrics");

    public static string MlbRefreshStats()
        => ApiUrlHelper.NormalizeRoute("odds/mlb/refresh-stats");

    public static string MlbTrain()
        => ApiUrlHelper.NormalizeRoute("odds/mlb/train");
}
