using System;

namespace SportsBettingAnalyzer.Shared.Services;

public static class ApiUrlHelper
{
    public static string NormalizeBaseUrl(string? baseUrl, string fallback = "http://localhost:8000")
    {
        var candidate = string.IsNullOrWhiteSpace(baseUrl) ? fallback : baseUrl.Trim();

        // If user enters host:port without a scheme, default to http.
        if (!candidate.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
            !candidate.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
        {
            candidate = $"http://{candidate}";
        }

        if (!Uri.TryCreate(candidate, UriKind.Absolute, out var uri))
        {
            uri = new Uri(fallback, UriKind.Absolute);
        }

        return uri.ToString().TrimEnd('/');
    }

    public static string NormalizeRoute(string route)
    {
        if (string.IsNullOrWhiteSpace(route))
        {
            return "/";
        }

        return route.StartsWith("/", StringComparison.Ordinal) ? route : $"/{route}";
    }

    public static Uri BuildAbsoluteUri(string? baseUrl, string route, string fallback = "http://localhost:8000")
    {
        var normalizedBase = NormalizeBaseUrl(baseUrl, fallback);
        var baseUri = new Uri($"{normalizedBase}/", UriKind.Absolute);
        return new Uri(baseUri, NormalizeRoute(route));
    }
}
