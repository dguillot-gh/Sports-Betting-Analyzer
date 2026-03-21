using Android.App;
using Android.Content.PM;
using Android.OS;

namespace SportsBettingAnalyzer.Mobile;

[Activity(Theme = "@style/Maui.SplashTheme", MainLauncher = true, ConfigurationChanges = ConfigChanges.ScreenSize | ConfigChanges.Orientation | ConfigChanges.UiMode | ConfigChanges.ScreenLayout | ConfigChanges.SmallestScreenSize | ConfigChanges.Density)]
public class MainActivity : MauiAppCompatActivity
{
    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        
        // Ensure default FirebaseApp is initialized so token generation works instantly
        try 
        {
            Firebase.FirebaseApp.InitializeApp(this);
        }
        catch 
        { 
            // Often if GoogleServicesJson auto-inits, this will throw "already exists" or similar.
            // It's safe to catch.
        }
    }
}
