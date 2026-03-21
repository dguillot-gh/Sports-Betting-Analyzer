using Microsoft.Extensions.Logging;
using System.Text;
using System.Text.Json;

namespace SportsBettingAnalyzer.Mobile.Services;

/// <summary>
/// Manages FCM push notification registration.
/// On startup: gets the FCM device token and registers it with the backend.
/// Listens for token refresh events and re-registers automatically.
/// </summary>
public class PushNotificationService
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<PushNotificationService> _logger;

    public PushNotificationService(HttpClient httpClient, ILogger<PushNotificationService> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    /// <summary>
    /// Call this once during app startup (e.g., from App.xaml.cs or MainPage).
    /// Retrieves the FCM token and sends it to the backend.
    /// </summary>
    public async Task RegisterAsync()
    {
        try
        {
#if ANDROID
            // Request notification permission on Android 13+
            if (Android.OS.Build.VERSION.SdkInt >= Android.OS.BuildVersionCodes.Tiramisu)
            {
                var status = await Permissions.CheckStatusAsync<Permissions.PostNotifications>();
                if (status != PermissionStatus.Granted)
                {
                    status = await Permissions.RequestAsync<Permissions.PostNotifications>();
                    if (status != PermissionStatus.Granted)
                    {
                        _logger.LogWarning("POST_NOTIFICATIONS permission denied.");
                        return;
                    }
                }
            }

            // Get the FCM token from Firebase
            var token = await Plugin.Firebase.CloudMessaging.CrossFirebaseCloudMessaging.Current.GetTokenAsync();
            _logger.LogInformation("FCM token acquired: {Token}", token?[..20] + "...");

            if (!string.IsNullOrEmpty(token))
            {
                await SendTokenToBackend(token);
            }

            // Listen for token refreshes
            Plugin.Firebase.CloudMessaging.CrossFirebaseCloudMessaging.Current.TokenChanged += async (sender, args) =>
            {
                _logger.LogInformation("FCM token refreshed, re-registering...");
                await SendTokenToBackend(args.Token);
            };

            // Handle foreground notifications
            Plugin.Firebase.CloudMessaging.CrossFirebaseCloudMessaging.Current.NotificationReceived += (sender, args) =>
            {
                var title = args.Notification.Title;
                var body = args.Notification.Body;

                var context = Android.App.Application.Context;
                var notificationManager = (Android.App.NotificationManager)context.GetSystemService(Android.Content.Context.NotificationService);

                var channelId = "default";
                if (Android.OS.Build.VERSION.SdkInt >= Android.OS.BuildVersionCodes.O)
                {
                    var channel = new Android.App.NotificationChannel(channelId, "Alerts", Android.App.NotificationImportance.High)
                    {
                        Description = "General notifications"
                    };
                    notificationManager.CreateNotificationChannel(channel);
                }

                // Get app icon resource ID dynamically
                int iconId = context.Resources.GetIdentifier("appicon", "mipmap", context.PackageName);
                if (iconId == 0) iconId = Android.Resource.Drawable.IcDialogInfo; // fallback

                var builder = new AndroidX.Core.App.NotificationCompat.Builder(context, channelId)
                    .SetContentTitle(title)
                    .SetContentText(body)
                    .SetSmallIcon(iconId)
                    .SetPriority(AndroidX.Core.App.NotificationCompat.PriorityHigh)
                    .SetAutoCancel(true);

                notificationManager.Notify(Guid.NewGuid().GetHashCode(), builder.Build());
            };
#endif
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to register for FCM push notifications.");
        }
    }

    private async Task SendTokenToBackend(string token)
    {
        try
        {
            var payload = new
            {
                device_token = token,
                platform = DeviceInfo.Platform.ToString().ToLower(),
                app_version = AppInfo.VersionString
            };

            var json = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("/admin/fcm/register", content);

            if (response.IsSuccessStatusCode)
            {
                _logger.LogInformation("FCM token registered with backend successfully.");
            }
            else
            {
                _logger.LogWarning("Backend rejected FCM token: {Status}", response.StatusCode);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to send FCM token to backend.");
        }
    }
}
