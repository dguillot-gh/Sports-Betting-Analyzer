using System.Net;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Tests
{
    public class ApiUrlHelperTests
    {
        [Theory]
        [InlineData(null, "http://localhost:8000")]
        [InlineData("", "http://localhost:8000")]
        [InlineData("   ", "http://localhost:8000")]
        [InlineData("myhost:9000", "http://myhost:9000")]
        [InlineData("https://prod.example.com", "https://prod.example.com")]
        [InlineData("http://host:8080/path/", "http://host:8080/path")]
        [InlineData("not a url at all", "http://localhost:8000")]
        public void NormalizeBaseUrl_HandlesSchemesTrailingSlashAndFallbacks(string? input, string expected)
        {
            Assert.Equal(expected, ApiUrlHelper.NormalizeBaseUrl(input));
        }

        [Theory]
        [InlineData(null, "/")]
        [InlineData("", "/")]
        [InlineData("health", "/health")]
        [InlineData("/health", "/health")]
        [InlineData("///x", "///x")]
        public void NormalizeRoute_PrefixesSlashOnce(string? route, string expected)
        {
            Assert.Equal(expected, ApiUrlHelper.NormalizeRoute(route!));
        }

        [Fact]
        public void BuildAbsoluteUri_CombinesBaseAndRoute()
        {
            var uri = ApiUrlHelper.BuildAbsoluteUri("http://host:8000", "nba/predict");
            Assert.Equal("http://host:8000/nba/predict", uri.ToString());
        }

        [Fact]
        public void BuildAbsoluteUri_RootBaseAndEmptyRoute()
        {
            var uri = ApiUrlHelper.BuildAbsoluteUri(null, "");
            Assert.Equal("http://localhost:8000/", uri.ToString());
        }
    }

    public class PredictionApiRoutesTests
    {
        [Fact]
        public void SportsbookRoutes_ContainEscapedQuery()
        {
            Assert.Equal("/odds/nba/analyze-cached?sportsbook=fanduel&include_cached=true",
                PredictionApiRoutes.NbaAnalyzeCached());
            Assert.Equal("/model-testing/nfl/predictions?sportsbook=betmgm",
                PredictionApiRoutes.NflPredictions("betmgm"));
        }

        [Fact]
        public void Sportsbook_IsUrlEncoded()
        {
            var route = PredictionApiRoutes.NhlAnalyzeAll("book & co");
            Assert.Contains("sportsbook=book%20%26%20co", route);
        }

        [Fact]
        public void NhlAnalyzeAll_Route() { Assert.Equal("/nhl/analyze-all?sportsbook=fanduel", PredictionApiRoutes.NhlAnalyzeAll()); }
        [Fact]
        public void CfbAnalyzeAll_Route() { Assert.Equal("/odds/cfb/analyze-all?sportsbook=fanduel", PredictionApiRoutes.CfbAnalyzeAll()); }
        [Fact]
        public void CollegeBaseballAnalyzeAll_Route() { Assert.Equal("/odds/college-baseball/analyze-all?sportsbook=fanduel", PredictionApiRoutes.CollegeBaseballAnalyzeAll()); }
        [Fact]
        public void MlbAnalyzeAll_Route() { Assert.Equal("/odds/mlb/analyze-all?sportsbook=fanduel", PredictionApiRoutes.MlbAnalyzeAll()); }
        [Fact]
        public void MlbTeamStats_Route() { Assert.Equal("/odds/mlb/team-stats", PredictionApiRoutes.MlbTeamStats()); }
        [Fact]
        public void MlbModelMetrics_Route() { Assert.Equal("/odds/mlb/model-metrics", PredictionApiRoutes.MlbModelMetrics()); }
        [Fact]
        public void MlbRefreshStats_Route() { Assert.Equal("/odds/mlb/refresh-stats", PredictionApiRoutes.MlbRefreshStats()); }
        [Fact]
        public void MlbTrain_Route() { Assert.Equal("/odds/mlb/train", PredictionApiRoutes.MlbTrain()); }
    }

    public class FakeVersionHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, Task<HttpResponseMessage>> _handler;

        public FakeVersionHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> handler)
        {
            _handler = handler;
        }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => _handler(request);
    }

    static class FakeVersionHttp
    {
        public static HttpClient Create(Func<HttpRequestMessage, Task<HttpResponseMessage>> handler)
            => new HttpClient(new FakeVersionHandler(handler));
    }

    public class FixedServerConfig : IServerConfigService
    {
        public string GetBaseUrl() => "http://example.invalid:8000";
        public void SetBaseUrl(string url) { }
    }

    public class VersionServiceTests
    {
        [Fact]
        public async Task DeserializesVersionInfo_WhenOk()
        {
            using var http = FakeVersionHttp.Create(req =>
                Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("{\"version\":\"1.2.3\",\"environment\":\"production\"}",
                        System.Text.Encoding.UTF8, "application/json")
                }));
            var svc = new VersionService(http, new FixedServerConfig());

            var info = await svc.GetVersionInfoAsync();
            Assert.Equal("1.2.3", info.Version);
            Assert.Equal("production", info.Environment);
        }

        [Fact]
        public async Task ReturnsErrorInfo_WhenHttpFails()
        {
            using var http = FakeVersionHttp.Create(req =>
                Task.FromResult(new HttpResponseMessage(HttpStatusCode.InternalServerError)));
            var svc = new VersionService(http, new FixedServerConfig());

            var info = await svc.GetVersionInfoAsync();

            Assert.Equal("Error", info.Version);
            Assert.Equal("Offline", info.Environment);
        }

        [Fact]
        public async Task EmptyBody_FallsToOfflineFallback()
        {
            // .NET's GetFromJsonAsync throws on empty content; VersionService maps
            // any failure to the offline fallback info.
            using var http = FakeVersionHttp.Create(req =>
                Task.FromResult(new HttpResponseMessage(HttpStatusCode.NoContent)));
            var svc = new VersionService(http, new FixedServerConfig());

            var info = await svc.GetVersionInfoAsync();
            Assert.Equal("Error", info.Version);
            Assert.Equal("Offline", info.Environment);
        }
    }
}
