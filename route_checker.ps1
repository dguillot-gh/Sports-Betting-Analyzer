$baseDir = "C:\Users\dguil\Documents\repo\Sports-Betting-Analyzer"
$projects = @("frontend", "mobile", "shared")

$routes = @()
$brokenLinks = @()

foreach ($p in $projects) {
    $files = Get-ChildItem -Path (Join-Path $baseDir $p) -Filter *.razor -Recurse
    foreach ($f in $files) {
        $content = Get-Content $f.FullName -Raw
        if ($null -eq $content) { continue }
        $matches = [regex]::Matches($content, '@page\s+"([^"]+)"')
        foreach ($m in $matches) {
            $route = $m.Groups[1].Value
            $baseRoute = $route.Split('{')[0].Trim('/')
            if ($baseRoute -eq "") {
                $routes += "/"
            } else {
                $routes += $baseRoute.ToLower()
            }
        }
    }
}
$routes += ""
$routes += "account/login"
$routes += "account/register"
$routes = $routes | Select-Object -Unique

foreach ($p in $projects) {
    $files = Get-ChildItem -Path (Join-Path $baseDir $p) -Include *.cs,*.razor -Recurse
    foreach ($f in $files) {
        $content = Get-Content $f.FullName -Raw
        if ($null -eq $content) { continue }
        $matches = [regex]::Matches($content, 'href="([^"]+)"')
        foreach ($m in $matches) {
            $link = $m.Groups[1].Value
            if ($link.StartsWith("http") -or $link.StartsWith("#") -or $link.StartsWith("mailto:")) {
                continue
            }
            $baseLink = $link.Split('?')[0].Split('#')[0].Trim('/').ToLower()
            $found = $false
            if ($routes -contains $baseLink) {
                $found = $true
            } else {
                foreach ($r in $routes) {
                    if ($r -ne "" -and $baseLink.StartsWith($r)) {
                        if ($baseLink.Length -gt $r.Length -and $baseLink[$r.Length] -eq '/') {
                            $found = $true
                            break
                        }
                    }
                }
            }
            if (-not $found) {
                $relPath = $f.FullName.Substring($baseDir.Length + 1)
                $brokenLinks += "$relPath -> $link"
            }
        }
    }
}

Write-Host "Found $($routes.Count) routes."
if ($brokenLinks.Count -eq 0) {
    Write-Host "All internal links appear to resolve to a valid page route!"
} else {
    Write-Host "Potential broken links found:"
    $brokenLinks | Select-Object -Unique | ForEach-Object { Write-Host $_ }
}
