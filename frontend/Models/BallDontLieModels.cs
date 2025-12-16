using System.Text.Json.Serialization;

namespace SportsBettingAnalyzer.Models
{
    public class BallDontLieResponse<T>
    {
        [JsonPropertyName("data")]
        public T Data { get; set; }

        [JsonPropertyName("meta")]
        public BallDontLieMeta Meta { get; set; }
    }

    public class BallDontLieMeta
    {
        [JsonPropertyName("next_cursor")]
        public int? NextCursor { get; set; }

        [JsonPropertyName("per_page")]
        public int PerPage { get; set; }
    }

    public class BallDontLieTeam
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }

        [JsonPropertyName("city")]
        public string City { get; set; }

        [JsonPropertyName("location")]
        public string Location { get; set; }

        [JsonPropertyName("conference")]
        public string Conference { get; set; }

        [JsonPropertyName("division")]
        public string Division { get; set; }

        [JsonPropertyName("full_name")]
        public string FullName { get; set; }

        [JsonPropertyName("name")]
        public string Name { get; set; }

        [JsonPropertyName("abbreviation")]
        public string Abbreviation { get; set; }
    }

    public class BallDontLieGame
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }

        [JsonPropertyName("date")]
        public string Date { get; set; }

        [JsonPropertyName("home_team")]
        public BallDontLieTeam HomeTeam { get; set; }

        [JsonPropertyName("visitor_team")]
        public BallDontLieTeam VisitorTeam { get; set; }

        [JsonPropertyName("home_team_score")]
        public int HomeTeamScore { get; set; }

        [JsonPropertyName("visitor_team_score")]
        public int VisitorTeamScore { get; set; }

        [JsonPropertyName("season")]
        public int Season { get; set; }

        [JsonPropertyName("period")]
        public int Period { get; set; }

        [JsonPropertyName("status")]
        public string Status { get; set; }
    }

    public class BallDontLiePlayer
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }

        [JsonPropertyName("first_name")]
        public string FirstName { get; set; }

        [JsonPropertyName("last_name")]
        public string LastName { get; set; }
        
        [JsonPropertyName("position")]
        public string Position { get; set; }
    }

    public class BallDontLiePlayerStat
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }

        [JsonPropertyName("pts")]
        public int Pts { get; set; }

        [JsonPropertyName("ast")]
        public int Ast { get; set; }

        [JsonPropertyName("reb")]
        public int Reb { get; set; }

        [JsonPropertyName("player")]
        public BallDontLiePlayer Player { get; set; }
        
        [JsonPropertyName("team")]
        public BallDontLieTeam Team { get; set; }
        
        [JsonPropertyName("game")]
        public BallDontLieGame Game { get; set; }
    }

    // Our aggregated stats model for UI
    public class TeamSeasonStats
    {
        public int TeamId { get; set; }
        public string TeamName { get; set; }
        public int GamesPlayed { get; set; }
        public double AveragePoints { get; set; }
        public double AveragePointsAllowed { get; set; }
        public int LastGameId { get; set; }
        
        // Last 5 games form (W/L)
        public List<string> RecentForm { get; set; } = new();
        
        // Average score in last 5
        public double RecentPoints { get; set; }
    }
}
