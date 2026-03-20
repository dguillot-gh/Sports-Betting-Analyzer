$SharedDir = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer\shared\Components"

$utf8NoBOM = New-Object System.Text.UTF8Encoding($false)

Write-Host "Updating shared Components @page directives..."
Get-ChildItem -Path $SharedDir -Filter "*.razor" | ForEach-Object {
    $content = [System.IO.File]::ReadAllText($_.FullName, $utf8NoBOM)
    $modified = $false
    
    # Check if the file contains @page "/..." and NOT @page "/" and NOT @page "/mobile-"
    if ($content -match '@page "/[^"]') {
        if ($content -notmatch '@page "/mobile-') {
            # Regex: match @page "/ and then capture the rest of the string until the closing quote
            $content = $content -replace '@page "/(.*)"', '@page "/mobile-$1"'
            $modified = $true
        }
    }
    
    if ($modified) {
        [System.IO.File]::WriteAllText($_.FullName, $content, $utf8NoBOM)
        Write-Host "Patched $($_.Name)"
    }
}

Write-Host "Done patching shared components."
