using System.Text.Json.Serialization;

namespace SportsBettingAnalyzer.Models
{
    public class DriverPrediction
    {
        [JsonPropertyName("driver_name")]
        public string DriverName { get; set; } = "";
        
        [JsonPropertyName("car_number")]
        public string CarNumber { get; set; } = "";
        
        [JsonPropertyName("win_probability")]
        public double WinProbability { get; set; }
        
        [JsonPropertyName("projected_finish")]
        public double ProjectedFinish { get; set; }
        
        [JsonPropertyName("market_odds")]
        public string MarketOdds { get; set; } = "N/A";
        
        [JsonPropertyName("confidence")]
        public string Confidence { get; set; } = "Low";
        
        public int Rank { get; set; }
    }
}
