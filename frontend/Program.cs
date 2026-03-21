using SportsBettingAnalyzer.Components;
using SportsBettingAnalyzer.Services;
using SportsBettingAnalyzer.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.AspNetCore.Components.Server;
using Microsoft.AspNetCore.DataProtection;
using MudBlazor.Services;

var builder = WebApplication.CreateBuilder(args);

// --- IMMEDIATE SETUP: Data Protection ---
// We do this first to ensure keys persist across container restarts
var keysPath = Path.Combine(builder.Environment.ContentRootPath, "keys");
if (!Directory.Exists(keysPath)) Directory.CreateDirectory(keysPath);
builder.Services.AddDataProtection()
    .PersistKeysToFileSystem(new DirectoryInfo(keysPath))
    .SetApplicationName("SportsBettingAnalyzer");
Console.WriteLine($"[SECURITY] Data Protection keys will be stored in: {keysPath}");
// ----------------------------------------

// Add services to the container.
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// Add MudBlazor
builder.Services.AddMudServices();

// Add Entity Framework
var dbPath = Path.Combine(builder.Environment.ContentRootPath, "sportsbetting.db");
builder.Services.AddDbContext<ApplicationDbContext>(options =>
    options.UseSqlite($"Data Source={dbPath}"));

// Add HTTP client factory for API calls
builder.Services.AddHttpClient();
builder.Services.AddHttpClient<ESPNDataProvider>().ConfigureHttpClient(c => c.Timeout = TimeSpan.FromMinutes(5));
builder.Services.AddHttpClient<WebScrapingDataProvider>().ConfigureHttpClient(c => c.Timeout = TimeSpan.FromMinutes(5));

// Configure Python ML Service client with extended timeout
builder.Services.Configure<PythonMLOptions>(builder.Configuration.GetSection("PythonMLService"));
builder.Services.AddHttpClient<PythonMLServiceClient>()
    .ConfigureHttpClient(client =>
    {
        client.Timeout = TimeSpan.FromMinutes(10); // Allow long-running training operations
    });

// Named HttpClient for direct usage in Blazor pages
var pythonServiceUrl = builder.Configuration["PythonMLService:BaseUrl"] ?? "http://localhost:8000";
builder.Services.AddHttpClient("PythonML", client =>
{
    client.BaseAddress = new Uri(pythonServiceUrl);
    client.Timeout = TimeSpan.FromMinutes(10);
});

// Add circuit options for better error handling and extended timeouts
builder.Services.AddServerSideBlazor()
    .AddCircuitOptions(options =>
    {
        // TEMPORARY: Force detailed errors for debugging circuit issues
        options.DetailedErrors = true;  // Was: builder.Environment.IsDevelopment();
        options.DisconnectedCircuitMaxRetained = 100;
        options.DisconnectedCircuitRetentionPeriod = TimeSpan.FromMinutes(10);
        options.JSInteropDefaultCallTimeout = TimeSpan.FromMinutes(5);
    });

// Add application services
builder.Services.AddScoped<StatisticalAnalysisService>();
builder.Services.AddScoped<MLModelService>();
builder.Services.AddScoped<BetAnalysisService>();
builder.Services.AddScoped<StatsScraperService>();
builder.Services.AddScoped<DataCollectionService>();
builder.Services.AddScoped<BetSlipOCRService>();
builder.Services.AddScoped<SportsDataService>();
builder.Services.AddScoped<HistoricalDataImportService>();
builder.Services.AddScoped<SportsBettingAnalyzer.Shared.Services.IServerConfigService, WebServerConfigService>();
builder.Services.AddScoped<SportsBettingAnalyzer.Shared.Services.IVersionService, SportsBettingAnalyzer.Shared.Services.VersionService>();

// (Data Protection config moved to top of file)

// Add external data providers
builder.Services.AddScoped<ESPNDataProvider>();
builder.Services.AddScoped<WebScrapingDataProvider>();
builder.Services.AddScoped<ExternalDataManager>();
builder.Services.AddScoped<SimulationStateService>();
builder.Services.AddScoped<FileExportService>();
builder.Services.AddHttpClient<OddsService>().ConfigureHttpClient(c => c.Timeout = TimeSpan.FromMinutes(10));
builder.Services.AddHttpClient<BallDontLieService>().ConfigureHttpClient(c => c.Timeout = TimeSpan.FromMinutes(5));
builder.Services.AddMemoryCache();

// Configure Tesseract data path
builder.Configuration["Tesseract:DataPath"] = Path.Combine(builder.Environment.ContentRootPath, "tessdata");

var app = builder.Build();

// Ensure database is created and optionally train ML model
using (var scope = app.Services.CreateScope())
{
    var dbContext = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
    dbContext.Database.EnsureCreated();

    // Auto-train ML model if there's enough data
    var dataCollectionService = scope.ServiceProvider.GetRequiredService<DataCollectionService>();
    var mlService = scope.ServiceProvider.GetRequiredService<MLModelService>();
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();

    try
    {
        var trainingBets = dataCollectionService.GetBetsForTrainingAsync().GetAwaiter().GetResult();
        if (trainingBets.Count >= 10)
        {
            mlService.TrainModel(trainingBets);
            logger.LogInformation("Auto-trained ML model on startup with {Count} bets", trainingBets.Count);
        }
    }
    catch (Exception ex)
    {
        // Log but don't fail startup if training fails
        logger.LogWarning(ex, "Failed to auto-train ML model on startup");
    }
}

// Configure the HTTP request pipeline.
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    // The default HSTS value is 30 days. You may want to change this for production scenarios, see https://aka.ms/aspnetcore-hsts.
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseAntiforgery();
app.MapStaticAssets();
app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

// Health check endpoint for Docker/Kubernetes
app.MapGet("/health", () => Results.Ok(new { 
    status = "healthy", 
    timestamp = DateTime.UtcNow,
    version = "1.0.0"
}));

app.Run();