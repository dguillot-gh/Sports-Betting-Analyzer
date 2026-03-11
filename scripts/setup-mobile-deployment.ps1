#!/usr/bin/env pwsh

# Sports Betting Analyzer - Mobile Deployment Setup Script
# This script helps set up Android keystore and GitHub secrets for mobile deployment

param(
    [Parameter(Mandatory=$false)]
    [string]$KeystorePath = "keystore.keystore",
    
    [Parameter(Mandatory=$false)]
    [string]$KeyAlias = "SportsBettingAnalyzer",
    
    [Parameter(Mandatory=$false)]
    [string]$CompanyName = "yourcompany"
)

Write-Host "🚀 Sports Betting Analyzer - Mobile Deployment Setup" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green

# Check if Java is installed
try {
    $javaVersion = java -version 2>&1
    Write-Host "✅ Java found: $javaVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Java not found. Please install Java JDK first." -ForegroundColor Red
    exit 1
}

# Check if keytool is available
try {
    $keytoolVersion = keytool -help
    Write-Host "✅ Keytool available" -ForegroundColor Green
} catch {
    Write-Host "❌ Keytool not found. Please ensure Java JDK is in PATH." -ForegroundColor Red
    exit 1
}

# Check if keystore already exists
if (Test-Path $KeystorePath) {
    Write-Host "⚠️  Keystore already exists at $KeystorePath" -ForegroundColor Yellow
    $overwrite = Read-Host "Do you want to overwrite it? (y/N)"
    if ($overwrite -ne "y" -and $overwrite -ne "Y") {
        Write-Host "Setup cancelled." -ForegroundColor Yellow
        exit 0
    }
    Remove-Item $KeystorePath -Force
}

# Generate keystore
Write-Host "🔐 Generating Android keystore..." -ForegroundColor Blue

# Collect keystore information
Write-Host "Please enter keystore information (or press Enter for defaults):" -ForegroundColor Cyan

$keystorePassword = Read-Host "Keystore password (min 6 chars)" -AsSecureString
if ($keystorePassword.Length -eq 0) {
    $keystorePassword = ConvertTo-SecureString "SportsBetting2024" -AsPlainText -Force
    Write-Host "Using default keystore password" -ForegroundColor Yellow
}

$keyPassword = Read-Host "Key password (or press Enter to use same as keystore)" -AsSecureString
if ($keyPassword.Length -eq 0) {
    $keyPassword = $keystorePassword
}

$dnameComponents = @()
$commonName = Read-Host "Common name (CN) [e.g., Your Name]"
if ($commonName) { $dnameComponents += "CN=$commonName" }

$orgUnit = Read-Host "Organizational unit (OU) [e.g., Mobile Development]"
if ($orgUnit) { $dnameComponents += "OU=$orgUnit" }

$orgName = Read-Host "Organization (O) [e.g., $CompanyName]"
if ($orgName) { $dnameComponents += "O=$orgName" } else { $dnameComponents += "O=$CompanyName" }

$city = Read-Host "City/Locality (L) [e.g., San Francisco]"
if ($city) { $dnameComponents += "L=$city" }

$state = Read-Host "State/Province (ST) [e.g., California]"
if ($state) { $dnameComponents += "ST=$state" }

$country = Read-Host "Country (C) [e.g., US]"
if ($country) { $dnameComponents += "C=$country" } else { $dnameComponents += "C=US" }

$dname = $dnameComponents -join ", "

# Build keytool command
$plainKeystorePassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($keystorePassword))
$plainKeyPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($keyPassword))

$command = @(
    "keytool"
    "-genkey"
    "-v"
    "-keystore", $KeystorePath
    "-alias", $KeyAlias
    "-keyalg", "RSA"
    "-keysize", "2048"
    "-validity", "10000"
    "-storepass", $plainKeystorePassword
    "-keypass", $plainKeyPassword
    "-dname", $dname
)

# Execute keytool command
Write-Host "Running: $($command -join ' ')" -ForegroundColor Gray
$result = & $command[0] $command[1..($command.Length-1)]

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Keystore created successfully: $KeystorePath" -ForegroundColor Green
    
    # Display keystore info
    Write-Host "`n📋 Keystore Information:" -ForegroundColor Cyan
    Write-Host "  File: $KeystorePath" -ForegroundColor White
    Write-Host "  Alias: $KeyAlias" -ForegroundColor White
    Write-Host "  Validity: 10000 days (~27 years)" -ForegroundColor White
    Write-Host "  Algorithm: RSA 2048-bit" -ForegroundColor White
    
    # Show GitHub secrets setup
    Write-Host "`n🔧 GitHub Secrets Setup:" -ForegroundColor Cyan
    Write-Host "  1. Go to your GitHub repository" -ForegroundColor White
    Write-Host "  2. Navigate to Settings → Secrets and variables → Actions" -ForegroundColor White
    Write-Host "  3. Add these secrets:" -ForegroundColor White
    Write-Host "" -ForegroundColor White
    Write-Host "     ANDROID_KEYSTORE_PASSWORD" -ForegroundColor Yellow
    Write-Host "     Value: $plainKeystorePassword" -ForegroundColor Gray
    Write-Host "" -ForegroundColor White
    Write-Host "     ANDROID_KEY_PASSWORD" -ForegroundColor Yellow
    Write-Host "     Value: $plainKeyPassword" -ForegroundColor Gray
    Write-Host "" -ForegroundColor White
    
    # Update project file
    $projectPath = "mobile/SportsBettingAnalyzer.Mobile.csproj"
    if (Test-Path $projectPath) {
        Write-Host "📱 Updating mobile project configuration..." -ForegroundColor Blue
        
        [xml]$projectXml = Get-Content $projectPath
        $propertyGroup = $projectXml.Project.PropertyGroup | Where-Object { $_.ApplicationId }
        
        if ($propertyGroup) {
            $propertyGroup.ApplicationId = "com.$CompanyName.sportsbettinganalyzer.mobile"
            $propertyGroup.ApplicationTitle = "Sports Betting Analyzer"
            $projectXml.Save($projectPath)
            Write-Host "✅ Updated project configuration" -ForegroundColor Green
        } else {
            Write-Host "⚠️  Could not find PropertyGroup in project file" -ForegroundColor Yellow
        }
    } else {
        Write-Host "⚠️  Project file not found: $projectPath" -ForegroundColor Yellow
    }
    
    # Security reminder
    Write-Host "`n🔒 Security Reminder:" -ForegroundColor Red
    Write-Host "  1. BACKUP your keystore file ($KeystorePath)" -ForegroundColor White
    Write-Host "  2. NEVER commit keystore to Git" -ForegroundColor White
    Write-Host "  3. Store passwords securely" -ForegroundColor White
    Write-Host "  4. Add keystore to .gitignore" -ForegroundColor White
    
    # Add to .gitignore if not already there
    $gitignorePath = ".gitignore"
    if (Test-Path $gitignorePath) {
        $gitignoreContent = Get-Content $gitignorePath
        if ($KeystorePath -notin $gitignoreContent) {
            Add-Content $gitignorePath "`n# Android keystore`n$KeystorePath"
            Write-Host "✅ Added keystore to .gitignore" -ForegroundColor Green
        }
    }
    
    Write-Host "`n🎉 Setup complete! You can now:" -ForegroundColor Green
    Write-Host "  • Test the mobile build workflow" -ForegroundColor White
    Write-Host "  • Push to develop branch for build testing" -ForegroundColor White
    Write-Host "  • Push to main branch for automatic releases" -ForegroundColor White
    
} else {
    Write-Host "❌ Failed to create keystore" -ForegroundColor Red
    Write-Host "Error: $result" -ForegroundColor Red
    exit 1
}

# Clear passwords from memory
$plainKeystorePassword = $null
$plainKeyPassword = $null
$keystorePassword = $null
$keyPassword = $null

Write-Host "`n✨ Done!" -ForegroundColor Green
