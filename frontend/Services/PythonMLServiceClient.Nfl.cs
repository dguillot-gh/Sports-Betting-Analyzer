// PythonMLServiceClient.Nfl.cs — part of PythonMLServiceClient (split for readability; public API unchanged).
using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using SportsBettingAnalyzer.Models;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Services;

// Nfl-specific ML service methods
public partial class PythonMLServiceClient
{

    public async Task<JsonElement?> PredictNflBatchAsync(object request)
    {
        try
        {
            var response = await _httpClient.PostAsJsonAsync("/odds/nfl/predict-batch", request);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning("NFL batch prediction request returned {StatusCode}", response.StatusCode);
                return null;
            }

            using var document = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync());
            return document.RootElement.Clone();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting NFL batch predictions for refreshed odds");
            return null;
        }
    }
}
