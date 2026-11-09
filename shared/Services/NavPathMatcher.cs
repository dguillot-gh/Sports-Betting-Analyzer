using System;

namespace SportsBettingAnalyzer.Shared.Services;

/// <summary>
/// Pure route-matching helpers for bottom/side navigation.
/// Kept framework-free so it can be unit-tested without a NavigationManager.
/// </summary>
public static class NavPathMatcher
{
    /// <summary>Sentinel used for the hamburger / menu toggle button (not a route).</summary>
    public const string MenuToggle = "MENU_TOGGLE";

    /// <summary>
    /// True when @currentPath is the @url itself or any page under it.
    /// Matching is case-insensitive and ignores leading/trailing slashes.
    /// Returns false for non-route sentinels like MENU_TOGGLE.
    /// </summary>
    public static bool IsActive(string? url, string? currentPath)
    {
        if (string.IsNullOrEmpty(url)) return false;
        if (url.Equals(MenuToggle, StringComparison.OrdinalIgnoreCase)) return false;

        var target = url.Trim('/').ToLowerInvariant();
        var current = currentPath?.Trim('/').ToLowerInvariant() ?? string.Empty;

        if (target.Length == 0) return current.Length == 0;
        return current == target || current.StartsWith(target + "/", StringComparison.Ordinal);
    }

    /// <summary>Normalizes a nav url to an absolute path ("/", "/nfl", "/nfl/scores").</summary>
    public static string ToAbsolutePath(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)) return "/";
        var trimmed = url.Trim();
        return trimmed.StartsWith("/", StringComparison.Ordinal) ? trimmed : "/" + trimmed;
    }
}
