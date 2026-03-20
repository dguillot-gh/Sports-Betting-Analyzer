$SharedDir = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\shared\Components"
$MobileHome = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\mobile\Components\Pages\Home.razor"
$MobileNav = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\mobile\Components\Layout\NavMenu.razor"

Write-Host "Updating shared Components @page directives..."
Get-ChildItem -Path $SharedDir -Filter "*.razor" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    
    # Only replace if it contains @page "/ and isn't just the root @page "/" nor already prefixed
    if ($content -match '@page "/[^"]' -and $content -notmatch '@page "/mobile-') {
        $newContent = $content -replace '@page "/', '@page "/mobile-'
        Set-Content -Path $_.FullName -Value $newContent -Encoding UTF8
        Write-Host "Patched $($_.Name)"
    }
}

Write-Host "Updating mobile href links..."
foreach ($file in @($MobileHome, $MobileNav)) {
    $content = Get-Content $file -Raw
    # We want to replace href="/something" with href="/mobile-something"
    # But NOT href="/" and NOT href="http..." and NOT already href="/mobile-"
    # Regex: replace href="/(not mobile-|not empty)"
    
    # A safer approach is to split by lines
    $lines = Get-Content $file
    $newLines = @()
    foreach ($line in $lines) {
        if ($line -match 'href="/[^"]' -and $line -notmatch 'href="/mobile-') {
            $line = $line -replace 'href="/', 'href="/mobile-'
        }
        $newLines += $line
    }
    Set-Content -Path $file -Value ($newLines -join "`n") -Encoding UTF8
    Write-Host "Patched $(Split-Path $file -Leaf)"
}

Write-Host "Done padding routes."
