using System.Text.Json.Serialization;

namespace SportsBettingAnalyzer.Shared.Models;

public class AppNotification
{
    [JsonPropertyName("id")]
    public long Id { get; set; }

    [JsonPropertyName("severity")]
    public string Severity { get; set; } = "info";

    [JsonPropertyName("category")]
    public string Category { get; set; } = "";

    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("source")]
    public string Source { get; set; } = "";

    [JsonPropertyName("created_at")]
    public DateTime CreatedAt { get; set; }

    [JsonPropertyName("read_at")]
    public DateTime? ReadAt { get; set; }
}

public class NotificationsResponse
{
    [JsonPropertyName("items")]
    public List<AppNotification> Items { get; set; } = new();

    [JsonPropertyName("count")]
    public int Count { get; set; }
}

public class UnreadCountResponse
{
    [JsonPropertyName("count")]
    public int Count { get; set; }
}
