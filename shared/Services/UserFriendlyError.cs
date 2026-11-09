using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace SportsBettingAnalyzer.Shared.Services;

/// <summary>
/// Converts raw exceptions into safe, user-facing error text.
/// Never exposes stack traces or internal details. The error id is a short,
/// deterministic token (hash of type + message) so support can correlate
/// repeated failures without leaking internals.
/// </summary>
public static class UserFriendlyError
{
    public const string GenericMessage = "Something went wrong while loading this page. Please try again.";
    public const string ConnectionMessage = "Could not connect to the server. Check your network and server settings, then try again.";
    public const string TimeoutMessage = "The server took too long to respond. Please try again in a moment.";
    public const string BadDataMessage = "The server returned data in an unexpected format. Please try again.";

    /// <summary>Returns a user-safe message for the (innermost) exception.</summary>
    public static string GetMessage(Exception? ex)
    {
        var current = Unwrap(ex);
        while (current?.InnerException is not null)
        {
            current = current.InnerException;
        }

        if (current is null) return GenericMessage;
        return current switch
        {
            HttpRequestException => ConnectionMessage,
            System.Net.Sockets.SocketException => ConnectionMessage,
            TimeoutException => TimeoutMessage,
            TaskCanceledException => TimeoutMessage,
            JsonException => BadDataMessage,
            UnauthorizedAccessException => ConnectionMessage,
            _ => GenericMessage
        };
    }

    /// <summary>Returns a stable 6-char id (e.g. "A1B2C3") for this exception's type + message.</summary>
    public static string GetErrorId(Exception? ex)
    {
        if (ex is null) return "000000";

        var root = ex;
        while (root.InnerException is not null) root = root.InnerException;

        var payload = Encoding.UTF8.GetBytes($"{root.GetType().FullName}:{root.Message}");
        var hash = SHA1.HashData(payload);
        var hex = Convert.ToHexString(hash.AsSpan(0, 3))!; // 6 hex chars
        return hex;
    }

    /// <summary>Unwraps aggregate exceptions to a single root cause.</summary>
    public static Exception? Unwrap(Exception? ex)
    {
        if (ex is AggregateException agg)
        {
            return Unwrap(agg.InnerExceptions.Count > 0 ? agg.InnerExceptions[0] : null);
        }
        return ex;
    }
}
