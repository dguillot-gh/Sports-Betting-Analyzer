
using System;
using System.Text.Json.Serialization;

namespace SportsBettingAnalyzer.Shared.Models
{
    public class ImportLog
    {
        [JsonPropertyName("id")]
        public int Id { get; set; }

        [JsonPropertyName("sport")]
        public string Sport { get; set; }

        [JsonPropertyName("status")]
        public string Status { get; set; }

        [JsonPropertyName("start_time")]
        public DateTime StartTime { get; set; }

        [JsonPropertyName("end_time")]
        public DateTime? EndTime { get; set; }

        [JsonPropertyName("duration_seconds")]
        public double? DurationSeconds { get; set; }

        [JsonPropertyName("rows_imported")]
        public int RowsImported { get; set; }

        [JsonPropertyName("new_rows_imported")]
        public int NewRowsImported { get; set; }

        [JsonPropertyName("updated_rows_imported")]
        public int UpdatedRowsImported { get; set; }

        [JsonPropertyName("files_processed")]
        public int FilesProcessed { get; set; }

        [JsonPropertyName("error_message")]
        public string ErrorMessage { get; set; }
    }
}
