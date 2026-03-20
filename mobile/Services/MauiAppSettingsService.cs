using Microsoft.Maui.Storage;
using SportsBettingAnalyzer.Shared.Models;
using SportsBettingAnalyzer.Shared.Services;
using System.Linq;
using System.Text.Json;

namespace SportsBettingAnalyzer.Mobile.Services;

public class MauiAppSettingsService : IAppSettingsService
{
    private const string BottomNavKey = "BottomNavItems";
    private static readonly Dictionary<string, string> LegacyRouteMap = new(StringComparer.OrdinalIgnoreCase)
    {
        [""] = "/",
        ["/"] = "/",
        ["home"] = "/",
        ["/home"] = "/",
        ["odds/nfl"] = "/mobile-odds/nfl",
        ["odds/nba"] = "/mobile-odds/nba",
        ["odds/nhl"] = "/mobile-odds/nhl",
        ["odds/ncaab"] = "/mobile-odds/ncaab",
        ["odds/cfb"] = "/mobile-odds/cfb",
        ["odds/college-baseball"] = "/mobile-odds/college-baseball",
        ["nascar/results"] = "/mobile-nascar/results",
        ["mobile-notifications"] = "/mobile-notifications",
        ["mobile-settings"] = "/mobile-settings",
        ["mobile-data-health"] = "/mobile-data-health",
        ["mobile-standings/nfl"] = "/mobile-standings/nfl",
        ["mobile-standings/nba"] = "/mobile-standings/nba",
        ["mobile-standings/nhl"] = "/mobile-standings/nhl"
    };

    public List<NavItem> GetAvailableNavItems()
    {
        return new List<NavItem>
        {
            new() { Label = "Home", Icon = "H", Url = "/" },
            new() { Label = "NFL Standings", Icon = "NFL", Url = "/standings/nfl" },
            new() { Label = "NBA Standings", Icon = "NBA", Url = "/standings/nba" },
            new() { Label = "NHL Standings", Icon = "NHL", Url = "/standings/nhl" },
            new() { Label = "Data Health", Icon = "D", Url = "/data-health" },
            new() { Label = "Notifications", Icon = "N", Url = "/mobile-notifications" },
            new() { Label = "Settings", Icon = "S", Url = "/settings" },
            new() { Label = "Menu", Icon = "M", Url = "MENU_TOGGLE" }
        };
    }

    public Task<List<NavItem>> GetBottomNavItemsAsync()
    {
        var json = Preferences.Get(BottomNavKey, "");
        if (string.IsNullOrEmpty(json))
        {
            return Task.FromResult(new List<NavItem>
            {
                new() { Label = "Home", Icon = "H", Url = "/" },
                new() { Label = "NFL", Icon = "NFL", Url = "/standings/nfl" },
                new() { Label = "NBA", Icon = "NBA", Url = "/standings/nba" },
                new() { Label = "Data", Icon = "D", Url = "/data-health" },
                new() { Label = "Menu", Icon = "M", Url = "MENU_TOGGLE" }
            });
        }

        try
        {
            var items = JsonSerializer.Deserialize<List<NavItem>>(json) ?? new List<NavItem>();
            var normalized = items
                .Select(item => new NavItem
                {
                    Label = item.Label,
                    Icon = item.Icon,
                    Url = NormalizeUrl(item.Url)
                })
                .Where(item => !string.IsNullOrWhiteSpace(item.Url))
                .Take(5)
                .ToList();

            if (normalized.Count == 0)
            {
                normalized = new List<NavItem>
                {
                    new() { Label = "Home", Icon = "H", Url = "/" },
                    new() { Label = "NFL", Icon = "NFL", Url = "/standings/nfl" },
                    new() { Label = "NBA", Icon = "NBA", Url = "/standings/nba" },
                    new() { Label = "Data", Icon = "D", Url = "/data-health" },
                    new() { Label = "Menu", Icon = "M", Url = "MENU_TOGGLE" }
                };
            }

            return Task.FromResult(normalized);
        }
        catch
        {
            return Task.FromResult(new List<NavItem>
            {
                new() { Label = "Home", Icon = "H", Url = "/" },
                new() { Label = "NFL", Icon = "NFL", Url = "/standings/nfl" },
                new() { Label = "NBA", Icon = "NBA", Url = "/standings/nba" },
                new() { Label = "Data", Icon = "D", Url = "/data-health" },
                new() { Label = "Menu", Icon = "M", Url = "MENU_TOGGLE" }
            });
        }
    }

    public Task SaveBottomNavItemsAsync(List<NavItem> items)
    {
        var normalized = items
            .Select(item => new NavItem
            {
                Label = item.Label,
                Icon = item.Icon,
                Url = NormalizeUrl(item.Url)
            })
            .Where(item => !string.IsNullOrWhiteSpace(item.Url))
            .Take(5)
            .ToList();

        var json = JsonSerializer.Serialize(normalized);
        Preferences.Set(BottomNavKey, json);
        return Task.CompletedTask;
    }

    private static string NormalizeUrl(string? url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            return "/";
        }

        if (url.Equals("MENU_TOGGLE", StringComparison.OrdinalIgnoreCase))
        {
            return "MENU_TOGGLE";
        }

        var cleaned = url.Trim();
        if (LegacyRouteMap.TryGetValue(cleaned, out var mapped))
        {
            return mapped;
        }

        if (!cleaned.StartsWith("/", StringComparison.Ordinal))
        {
            cleaned = "/" + cleaned;
        }

        return cleaned;
    }
}
