using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services;

public class SimulationStateService
{
    private readonly PythonMLServiceClient _mlClient;
    
    public SimulationStateService(PythonMLServiceClient mlClient)
    {
        _mlClient = mlClient;
    }

    public List<DriverRoster> Drivers { get; private set; } = new();
    public bool IsInitialized => Drivers.Any();

    public async Task LoadRosterAsync(string series = "cup", int minRaces = 1, int? year = null)
    {
        try 
        {
            Drivers = await _mlClient.GetRosterAsync("nascar", series, minRaces, year);
        }
        catch (Exception)
        {
            // Fallback or empty list on error
            Drivers = new List<DriverRoster>();
        }
    }

    public void ToggleSelection(string driverName)
    {
        var driver = Drivers.FirstOrDefault(d => d.Name == driverName);
        if (driver != null)
        {
            driver.IsSelected = !driver.IsSelected;
        }
    }

    public void SelectAll()
    {
        foreach (var driver in Drivers)
        {
            driver.IsSelected = true;
        }
    }

    public void DeselectAll()
    {
        foreach (var driver in Drivers)
        {
            driver.IsSelected = false;
        }
    }

    public List<string> GetSelectedDriverNames()
    {
        return Drivers.Where(d => d.IsSelected).Select(d => d.Name).ToList();
    }
}
