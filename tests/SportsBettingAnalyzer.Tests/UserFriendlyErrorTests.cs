using System.Net;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Tests;

public class UserFriendlyErrorTests
{
    [Fact]
    public void GetMessage_Null_ReturnsGenericMessage()
    {
        Assert.Equal(UserFriendlyError.GenericMessage, UserFriendlyError.GetMessage(null));
    }

    [Theory]
    [InlineData(typeof(HttpRequestException))]
    [InlineData(typeof(UnauthorizedAccessException))]
    public void GetMessage_ConnectionErrors_ReturnConnectionMessage(Type exType)
    {
        var ex = (Exception)Activator.CreateInstance(exType, "boom")!;
        Assert.Equal(UserFriendlyError.ConnectionMessage, UserFriendlyError.GetMessage(ex));
    }

    [Fact]
    public void GetMessage_Timeout_ReturnsTimeoutMessage()
    {
        Assert.Equal(UserFriendlyError.TimeoutMessage, UserFriendlyError.GetMessage(new TimeoutException()));
    }

    [Fact]
    public void GetMessage_TaskCanceled_ReturnsTimeoutMessage()
    {
        var ex = new TaskCanceledException("canceled");
        Assert.Equal(UserFriendlyError.TimeoutMessage, UserFriendlyError.GetMessage(ex));
    }

    [Fact]
    public void GetMessage_JsonError_ReturnsBadDataMessage()
    {
        var ex = new System.Text.Json.JsonException("bad json");
        Assert.Equal(UserFriendlyError.BadDataMessage, UserFriendlyError.GetMessage(ex));
    }

    [Fact]
    public void GetMessage_GenericException_ReturnsGenericMessage()
    {
        Assert.Equal(UserFriendlyError.GenericMessage, UserFriendlyError.GetMessage(new InvalidOperationException("secret internals")));
    }

    [Fact]
    public void GetMessage_WrapsInnerException_MapsRootCause()
    {
        var inner = new HttpRequestException("DNS failure");
        var outer = new InvalidOperationException("outer", inner);
        Assert.Equal(UserFriendlyError.ConnectionMessage, UserFriendlyError.GetMessage(outer));
    }

    [Fact]
    public void GetMessage_AggregateException_MapsRootCause()
    {
        var inner = new TimeoutException();
        var agg = new AggregateException("wrapping", inner);
        Assert.Equal(UserFriendlyError.TimeoutMessage, UserFriendlyError.GetMessage(agg));
    }

    [Fact]
    public void GetMessage_NeverLeaksOriginalMessage()
    {
        var ex = new InvalidOperationException("password=hunter2 C:\\Users\\secret");
        var message = UserFriendlyError.GetMessage(ex);
        Assert.DoesNotContain("hunter2", message);
        Assert.DoesNotContain("C:\\Users", message);
    }

    [Fact]
    public void GetErrorId_IsSixHexChars()
    {
        var id = UserFriendlyError.GetErrorId(new InvalidOperationException("x"));
        Assert.Matches("^[0-9A-F]{6}$", id);
    }

    [Fact]
    public void GetErrorId_IsStableForSameException_DifferentAcrossMessages()
    {
        var id1 = UserFriendlyError.GetErrorId(new InvalidOperationException("a"));
        var id2 = UserFriendlyError.GetErrorId(new InvalidOperationException("a"));
        var id3 = UserFriendlyError.GetErrorId(new InvalidOperationException("b"));
        Assert.Equal(id1, id2);
        Assert.NotEqual(id1, id3);
    }

    [Fact]
    public void GetErrorId_Null_ReturnsZeroId()
    {
        Assert.Equal("000000", UserFriendlyError.GetErrorId(null));
    }
}
