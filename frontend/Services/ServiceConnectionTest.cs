using System;
using System.Net.Http;
using System.Threading.Tasks;

namespace ServiceTest;

class Program
{
    static async Task Main()
    {
   Console.WriteLine("?? Python ML Service Connection Test\n");
        Console.WriteLine("=" + new string('=', 60));
        
      // Test 1: Port availability
        await TestPortAvailability();
   
   // Test 2: HTTP connection
        await TestHttpConnection();

        // Test 3: Health endpoint
        await TestHealthEndpoint();
        
        Console.WriteLine("=" + new string('=', 60));
    }
    
    static async Task TestPortAvailability()
  {
        Console.WriteLine("\n? Test 1: Checking if port 8000 is accessible...");
      try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
       var response = await client.GetAsync("http://localhost:8000");
       Console.WriteLine($"  ? Port 8000 is accessible (Status: {response.StatusCode})");
        }
        catch (HttpRequestException)
        {
            Console.WriteLine($"  ? Port 8000 is NOT accessible");
         Console.WriteLine($"  ? Make sure Python service is running");
    Console.WriteLine($"  ? Command: python -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000");
    }
        catch (TaskCanceledException)
        {
         Console.WriteLine($"  ? Timeout connecting to port 8000");
            Console.WriteLine($"  ? Service may be too slow to respond");
        }
    }
    
    static async Task TestHttpConnection()
    {
   Console.WriteLine("\n? Test 2: HTTP connectivity...");
        try
        {
            using var client = new HttpClient();
            client.BaseAddress = new Uri("http://localhost:8000");
     var response = await client.GetAsync("/");
            Console.WriteLine($"  ? HTTP connection successful");
        }
      catch (Exception ex)
        {
          Console.WriteLine($"  ? HTTP connection failed: {ex.Message}");
        }
  }
    
    static async Task TestHealthEndpoint()
    {
     Console.WriteLine("\n? Test 3: Python service /health endpoint...");
        try
  {
   using var client = new HttpClient();
            var response = await client.GetAsync("http://localhost:8000/health");
            
          if (response.IsSuccessStatusCode)
 {
         var content = await response.Content.ReadAsStringAsync();
     Console.WriteLine($"  ? Health endpoint responding");
       Console.WriteLine($"  Response: {content}");
            }
            else
  {
     Console.WriteLine($"  ??  Health endpoint returned: {response.StatusCode}");
    }
        }
        catch (HttpRequestException ex)
        {
       Console.WriteLine($"  ? Cannot reach /health endpoint");
         Console.WriteLine($"  Error: {ex.Message}");
  Console.WriteLine($"\n  SOLUTION:");
 Console.WriteLine($"  1. Open new PowerShell window");
     Console.WriteLine($"  2. cd C:\\Users\\dguil\\source\\repos\\PythonMLService");
        Console.WriteLine($"  3. env\\Scripts\\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000");
     Console.WriteLine($"  4. Keep that window open");
}
        catch (TaskCanceledException)
     {
          Console.WriteLine($"  ? Timeout - service not responding");
 }
    }
}
