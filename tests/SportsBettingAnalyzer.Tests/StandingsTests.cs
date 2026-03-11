using Xunit;
using SportsBettingAnalyzer.Shared.Components;
using System.Text.Json;

namespace SportsBettingAnalyzer.Tests
{
    public class StandingsTests
    {
        [Fact]
        public void StandingsEntry_Deserilization_Works()
        {
            // Simulate optimized JSON from backend
            var json = @"{
                ""team"": ""LA Lakers"",
                ""wins"": 45,
                ""losses"": 30,
                ""points_for"": 8500,
                ""points_against"": 8200,
                ""win_pct"": 0.600,
                ""record"": ""45-30""
            }";

            var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
            var entry = JsonSerializer.Deserialize<LeagueStandings.StandingsEntry>(json, options);

            Assert.NotNull(entry);
            Assert.Equal("LA Lakers", entry.Team);
            Assert.Equal(45, entry.Wins);
            Assert.Equal(30, entry.Losses);
            Assert.Equal("45-30", entry.Record);
        }

        [Fact]
        public void StandingsResponse_Parsing_Works()
        {
            var json = @"{
                ""sport"": ""nba"",
                ""season"": 2024,
                ""standings"": [
                    { ""team"": ""Celtics"", ""wins"": 60, ""losses"": 22, ""record"": ""60-22"" }
                ]
            }";

            var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
            var response = JsonSerializer.Deserialize<LeagueStandings.StandingsResponse>(json, options);

            Assert.NotNull(response);
            Assert.Equal("nba", response.Sport);
            Assert.Single(response.Standings);
            Assert.Equal("Celtics", response.Standings[0].Team);
        }
    }
}
