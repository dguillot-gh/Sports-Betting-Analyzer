using Microsoft.Maui.Storage;
using SportsBettingAnalyzer.Shared.Models;
using SportsBettingAnalyzer.Shared.Services;
using System.Text.Json;

namespace SportsBettingAnalyzer.Mobile.Services;

public class MauiAppSettingsService : IAppSettingsService
{
    private const string BottomNavKey = "BottomNavItems";

    public List<NavItem> GetAvailableNavItems()
    {
        return new List<NavItem>
        {
            new() { Label = "Home", Icon = "🏠", Url = "" },
            new() { Label = "NBA Odds", Icon = "🏀", Url = "odds/nba" },
            new() { Label = "NHL Odds", Icon = "🏒", Url = "odds/nhl" },
            new() { Label = "NFL Odds", Icon = "🏈", Url = "odds/nfl" },
            new() { Label = "NASCAR", Icon = "🏁", Url = "nascar/results" },
            new() { Label = "Standings", Icon = "🏆", Url = "nascar/standings" },
            new() { Label = "Scan", Icon = "🌐", Url = "all-sports" },
            new() { Label = "Bets", Icon = "📋", Url = "bet-tracker" },
            new() { Label = "Trade", Icon = "💸", Url = "paper-trading" },
            new() { Label = "Weather", Icon = "☁️", Url = "weather" },
            new() { Label = "Settings", Icon = "⚙️", Url = "settings" }
        };
    }

    public async Task<List<NavItem>> GetBottomNavItemsAsync()
    {
        var json = Preferences.Get(BottomNavKey, "");
        if (string.IsNullOrEmpty(json))
        {
            // Default items
            return new List<NavItem>
            {
                new() { Label = "Home", Icon = "🏠", Url = "" },
                new() { Label = "NBA", Icon = "🏀", Url = "odds/nba" },
                new() { Label = "NASCAR", Icon = "🏁", Url = "nascar/results" },
                new() { Label = "Standings", Icon = "🏆", Url = "nascar/standings" },
                new() { Label = "Menu", Icon = "☰", Url = "MENU_TOGGLE" } // Special item for menu
            };
        }

        try
        {
            return JsonSerializer.Deserialize<List<NavItem>>(json) ?? new List<NavItem>();
        }
        catch
        {
            return new List<NavItem>();
        }
    }

    public async Task SaveBottomNavItemsAsync(List<NavItem> items)
    {
        var json = JsonSerializer.Serialize(items);
        Preferences.Set(BottomNavKey, json);
    }
}
