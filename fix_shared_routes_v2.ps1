$SharedDir = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\shared\Components"
$MobileHome = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\mobile\Components\Pages\Home.razor"
$MobileNav = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\mobile\Components\Layout\NavMenu.razor"

$utf8NoBOM = New-Object System.Text.UTF8Encoding($false)

Write-Host "Updating shared Components @page directives..."
Get-ChildItem -Path $SharedDir -Filter "*.razor" | ForEach-Object {
    $content = [System.IO.File]::ReadAllText($_.FullName, $utf8NoBOM)
    $modified = $false
    
    if ($content -match '^@page "/[^"]') {
        if ($content -notmatch '^@page "/mobile-') {
            # Use specific replace on the @page line to avoid matching random text
            $content = $content -replace '(?m)^@page "/(.*)"$', '@page "/mobile-$1"'
            $modified = $true
        }
    }
    
    if ($modified) {
        [System.IO.File]::WriteAllText($_.FullName, $content, $utf8NoBOM)
        Write-Host "Patched $($_.Name)"
    }
}

Write-Host "Updating mobile href links..."
foreach ($file in @($MobileHome, $MobileNav)) {
    $lines = [System.IO.File]::ReadAllLines($file, $utf8NoBOM)
    
    $newLines = @()
    foreach ($line in $lines) {
        if ($line -match 'href="/[^"]' -and $line -notmatch 'href="/mobile-') {
            $line = $line -replace 'href="/(.*)"', 'href="/mobile-$1"'
        }
        $newLines += $line
    }
    
    [System.IO.File]::WriteAllLines($file, $newLines, $utf8NoBOM)
    Write-Host "Patched $(Split-Path $file -Leaf)"
}

Write-Host "Done safely padding routes."
