using Microsoft.AspNetCore.Components;
using Microsoft.JSInterop;

namespace frontend.Services;

/// <summary>
/// Detects if user is on mobile device and handles auto-redirect to mobile routes.
/// </summary>
public class DeviceDetectionService
{
    private readonly IJSRuntime _js;
    private readonly NavigationManager _nav;
    private bool? _isMobile;

    public DeviceDetectionService(IJSRuntime js, NavigationManager nav)
    {
        _js = js;
        _nav = nav;
    }

    public async Task<bool> IsMobileDevice()
    {
        if (_isMobile.HasValue) return _isMobile.Value;
        
        try
        {
            _isMobile = await _js.InvokeAsync<bool>("isMobileDevice");
        }
        catch
        {
            _isMobile = false;
        }
        return _isMobile.Value;
    }

    public async Task RedirectIfMobile()
    {
        if (await IsMobileDevice())
        {
            var uri = _nav.Uri;
            
            // Don't redirect if already on mobile route or explicitly on desktop
            if (uri.Contains("/m/") || uri.Contains("?desktop=true")) return;
            
            // Map desktop routes to mobile routes
            var path = new Uri(uri).AbsolutePath;
            var mobileRoute = path switch
            {
                "/" => "/m/live-odds",
                "/live-odds" => "/m/live-odds",
                "/live-nfl-odds" => "/m/live-nfl-odds",
                "/analytics" => "/m/analytics",
                "/trends" => "/m/trends",
                "/history" => "/m/history",
                "/nba-hit-rates" or "/nfl-hit-rates" => "/m/hit-rates",
                "/nba-game-results" or "/nfl-game-results" => "/m/game-results",
                "/nba-player-profiles" or "/nfl-player-profiles" => "/m/player-profiles",
                _ => null
            };
            
            if (mobileRoute != null)
            {
                _nav.NavigateTo(mobileRoute);
            }
        }
    }
}
