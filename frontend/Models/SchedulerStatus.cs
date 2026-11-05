using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SportsBettingAnalyzer.Models
{
    public class SchedulerStatus
    {
        [JsonPropertyName("generatedAt")]
        public string GeneratedAt { get; set; }

        [JsonPropertyName("summary")]
        public Dictionary<string, int> Summary { get; set; } = new();

        [JsonPropertyName("sports")]
        public List<SchedulerStatusSport> Sports { get; set; } = new();

        [JsonPropertyName("recentRuns")]
        public List<SchedulerStatusRun> RecentRuns { get; set; } = new();
    }

    public class SchedulerStatusSport
    {
        [JsonPropertyName("sport")]
        public string Sport { get; set; }

        [JsonPropertyName("health")]
        public string Health { get; set; }  // healthy | degraded | down | never_run

        [JsonPropertyName("lastStatus")]
        public string LastStatus { get; set; }

        [JsonPropertyName("lastRunAt")]
        public string LastRunAt { get; set; }

        [JsonPropertyName("ageMinutes")]
        public double? AgeMinutes { get; set; }

        [JsonPropertyName("durationSeconds")]
        public double? DurationSeconds { get; set; }

        [JsonPropertyName("rowsImported")]
        public int RowsImported { get; set; }

        [JsonPropertyName("error")]
        public string Error { get; set; }

        [JsonPropertyName("consecutiveFailures")]
        public int ConsecutiveFailures { get; set; }

        [JsonPropertyName("totalRuns")]
        public int TotalRuns { get; set; }
    }

    public class SchedulerStatusRun
    {
        [JsonPropertyName("sport")]
        public string Sport { get; set; }

        [JsonPropertyName("status")]
        public string Status { get; set; }

        [JsonPropertyName("start_time")]
        public string StartTime { get; set; }

        [JsonPropertyName("rows_imported")]
        public int RowsImported { get; set; }

        [JsonPropertyName("error")]
        public string Error { get; set; }
    }
}
