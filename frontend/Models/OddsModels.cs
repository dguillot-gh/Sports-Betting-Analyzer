using System.Text.Json.Serialization;

namespace SportsBettingAnalyzer.Models
{
    public class SportInfo
    {
        [JsonPropertyName("key")]
        public string Key { get; set; } = "";

        [JsonPropertyName("group")]
        public string Group { get; set; } = "";

        [JsonPropertyName("title")]
        public string Title { get; set; } = "";

        [JsonPropertyName("description")]
        public string Description { get; set; } = "";

        [JsonPropertyName("active")]
        public bool Active { get; set; }

        [JsonPropertyName("has_outrights")]
        public bool HasOutrights { get; set; }
    }

    public class OddsEvent
    {
        [JsonPropertyName("id")]
        public string Id { get; set; } = "";

        [JsonPropertyName("sport_key")]
        public string SportKey { get; set; } = "";

        [JsonPropertyName("sport_title")]
        public string SportTitle { get; set; } = "";

        [JsonPropertyName("commence_time")]
        public DateTime CommenceTime { get; set; }

        [JsonPropertyName("home_team")]
        public string HomeTeam { get; set; } = "";

        [JsonPropertyName("away_team")]
        public string AwayTeam { get; set; } = "";

        [JsonPropertyName("bookmakers")]
        public List<Bookmaker> Bookmakers { get; set; } = new();
    }

    public class Bookmaker
    {
        [JsonPropertyName("key")]
        public string Key { get; set; } = "";

        [JsonPropertyName("title")]
        public string Title { get; set; } = "";

        [JsonPropertyName("last_update")]
        public DateTime LastUpdate { get; set; }

        [JsonPropertyName("markets")]
        public List<Market> Markets { get; set; } = new();
    }

    public class Market
    {
        [JsonPropertyName("key")]
        public string Key { get; set; } = "";

        [JsonPropertyName("last_update")]
        public DateTime LastUpdate { get; set; }

        [JsonPropertyName("outcomes")]
        public List<Outcome> Outcomes { get; set; } = new();
    }

    public class Outcome
    {
        [JsonPropertyName("name")]
        public string Name { get; set; } = "";

        [JsonPropertyName("price")]
        public double Price { get; set; }

        [JsonPropertyName("point")]
        public double? Point { get; set; }
    }

    public class QuotaInfo
    {
        public int RequestsRemaining { get; set; }
        public int RequestsUsed { get; set; }
        public int RequestsLast { get; set; }
    }
}
