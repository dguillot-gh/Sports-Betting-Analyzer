using System.Text.Json.Serialization;
using System.Collections.Generic;

namespace SportsBettingAnalyzer.Mobile.Models
{
    /// <summary>
    /// Deployment version information from backend API
    /// </summary>
    public class DeploymentVersionInfo
    {
        [JsonPropertyName("version")]
        public string Version { get; set; } = string.Empty;

        [JsonPropertyName("git_sha")]
        public string GitSha { get; set; } = string.Empty;

        [JsonPropertyName("git_branch")]
        public string GitBranch { get; set; } = string.Empty;

        [JsonPropertyName("build_time")]
        public string BuildTime { get; set; } = string.Empty;

        [JsonPropertyName("environment")]
        public string Environment { get; set; } = string.Empty;

        [JsonPropertyName("deployment_id")]
        public string DeploymentId { get; set; } = string.Empty;

        [JsonPropertyName("components")]
        public List<DeploymentComponent> Components { get; set; } = new();
    }

    /// <summary>
    /// Deployment component information
    /// </summary>
    public class DeploymentComponent
    {
        [JsonPropertyName("component_name")]
        public string ComponentName { get; set; } = string.Empty;

        [JsonPropertyName("component_version")]
        public string ComponentVersion { get; set; } = string.Empty;

        [JsonPropertyName("component_sha")]
        public string ComponentSha { get; set; } = string.Empty;

        [JsonPropertyName("status")]
        public string Status { get; set; } = string.Empty;
    }
}
