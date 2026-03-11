
using System;

namespace SportsBettingAnalyzer.Shared.Models
{
    public class ImportLog
    {
        public int Id { get; set; }
        public string Sport { get; set; }
        public string Status { get; set; }
        public DateTime StartTime { get; set; }
        public DateTime? EndTime { get; set; }
        public double? DurationSeconds { get; set; }
        public int RowsImported { get; set; }
        public int NewRowsImported { get; set; }
        public int UpdatedRowsImported { get; set; }
        public int FilesProcessed { get; set; }
        public string ErrorMessage { get; set; }
    }
}
