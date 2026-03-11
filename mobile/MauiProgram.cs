using Microsoft.Extensions.Logging;
using SportsBettingAnalyzer.Shared.Services;
using SportsBettingAnalyzer.Mobile.Services;

namespace SportsBettingAnalyzer.Mobile;

public static class MauiProgram
{
	public static MauiApp CreateMauiApp()
	{
		var builder = MauiApp.CreateBuilder();
		builder
			.UseMauiApp<App>()
			.ConfigureFonts(fonts =>
			{
				fonts.AddFont("OpenSans-Regular.ttf", "OpenSansRegular");
			});

		builder.Services.AddMauiBlazorWebView();

		builder.Services.AddSingleton<IServerConfigService, MauiServerConfigService>();
		builder.Services.AddSingleton<IAppSettingsService, MauiAppSettingsService>();
		builder.Services.AddScoped<IVersionService, VersionService>();

		builder.Services.AddScoped(sp => 
		{
			var configService = sp.GetRequiredService<IServerConfigService>();
			var baseUrl = configService.GetBaseUrl();
			return new HttpClient { BaseAddress = new Uri(baseUrl) };
		});

#if DEBUG
		builder.Services.AddBlazorWebViewDeveloperTools();
		builder.Logging.AddDebug();
#endif

		return builder.Build();
	}
}
