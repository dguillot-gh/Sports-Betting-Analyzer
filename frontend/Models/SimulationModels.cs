namespace SportsBettingAnalyzer.Models;

public class DriverRoster
{
    [System.Text.Json.Serialization.JsonPropertyName("name")]
    public string Name { get; set; } = "";
    
    [System.Text.Json.Serialization.JsonPropertyName("team")]
    public string Team { get; set; } = "";
    
    [System.Text.Json.Serialization.JsonPropertyName("manufacturer")]
    public string Manufacturer { get; set; } = "";
    
    [System.Text.Json.Serialization.JsonPropertyName("races_2024")]
    public int Races2024 { get; set; }
    
    [System.Text.Json.Serialization.JsonPropertyName("races_2025")]
    public int Races2025 { get; set; }
    
    [System.Text.Json.Serialization.JsonPropertyName("total_races")]
    public int TotalRaces { get; set; }
    
    public bool IsSelected { get; set; } = true;
}
