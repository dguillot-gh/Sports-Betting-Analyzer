using SportsBettingAnalyzer.Mobile.Services;

namespace SportsBettingAnalyzer.Mobile;

public partial class App : Application
{
    private readonly PushNotificationService _pushService;

	public App(PushNotificationService pushService)
	{
		InitializeComponent();
        _pushService = pushService;
	}

	protected override Window CreateWindow(IActivationState? activationState)
	{
		return new Window(new MainPage()) { Title = "SportsBettingAnalyzer.Mobile" };
	}

    protected override async void OnStart()
    {
        base.OnStart();
        await _pushService.RegisterAsync();
    }
}
