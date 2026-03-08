using SportsBettingAnalyzer.Shared.Models;

namespace SportsBettingAnalyzer.Shared.Services;

public interface IAppSettingsService
{
    Task<List<NavItem>> GetBottomNavItemsAsync();
    Task SaveBottomNavItemsAsync(List<NavItem> items);
    List<NavItem> GetAvailableNavItems();
}
