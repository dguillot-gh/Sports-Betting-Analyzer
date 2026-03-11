# Mobile App Deployment Setup Guide

This guide explains how to set up automatic APK building and deployment for the Sports Betting Analyzer mobile app using GitHub Actions.

## 🚀 Overview

The GitHub Actions workflow will:
- Automatically build the Android APK on every push to `main` or `develop` branches
- Generate semantic versions automatically
- Create GitHub Releases with APK downloads
- Support manual releases via workflow dispatch

## 📋 Prerequisites

1. **Android Keystore** (for signing the APK)
2. **GitHub Repository Secrets**
3. **Optional**: Apple Developer account (for iOS builds)

## 🔧 Setup Instructions

### 1. Create Android Keystore

Create a keystore for signing your Android APK:

```bash
# Create keystore (run once)
keytool -genkey -v -keystore keystore.keystore -alias SportsBettingAnalyzer -keyalg RSA -keysize 2048 -validity 10000

# This will create: keystore.keystore
# Keep this file secure and never commit it to git!
```

### 2. Configure GitHub Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions and add these secrets:

#### Required for Android:
```
ANDROID_KEYSTORE_PASSWORD
- The password you set when creating the keystore

ANDROID_KEY_PASSWORD  
- The password for the key alias (usually same as keystore password)
```

#### Optional for iOS (when enabled):
```
IOS_PROVISIONING_PROFILE
- Base64 encoded .mobileprovision file

IOS_CERTIFICATE
- Base64 encoded .p12 certificate file

IOS_CERTIFICATE_PASSWORD
- Password for the iOS certificate
```

### 3. Update App Configuration

Edit `mobile/SportsBettingAnalyzer.Mobile.csproj` to set your app details:

```xml
<ApplicationId>com.yourcompany.sportsbettinganalyzer</ApplicationId>
<ApplicationTitle>Sports Betting Analyzer</ApplicationTitle>
<ApplicationDisplayVersion>1.0</ApplicationDisplayVersion>
<ApplicationVersion>1</ApplicationVersion>
```

### 4. Test the Workflow

#### Automatic Build:
```bash
# Push to main branch (triggers automatic build and release)
git push origin main

# Push to develop branch (triggers build only)
git push origin develop
```

#### Manual Release:
1. Go to Actions tab in GitHub
2. Select "Build and Deploy Mobile App" workflow
3. Click "Run workflow"
4. Check "Create GitHub Release"
5. Click "Run workflow"

## 📱 Installation Instructions

### For Users:

1. **Download APK**: From GitHub Releases page
2. **Enable Unknown Sources**: 
   - Android 8+: Settings → Apps → Special access → Install unknown apps
   - Android 7: Settings → Security → Unknown sources
3. **Install APK**: Tap the downloaded file
4. **Launch App**: Grant necessary permissions

### For Developers:

```bash
# Download from GitHub Actions artifacts
# Or from the latest GitHub Release
```

## 🔄 Version Management

The workflow automatically generates semantic versions:
- **Format**: `YYYY.MM.DD.COMMIT_COUNT`
- **Example**: `2026.03.09.42`
- **Android Version Code**: `YYYYMMDDCC` format

### Version Examples:
- `2026.03.09.42` → March 9, 2026, 42nd commit
- `2026.03.10.45` → March 10, 2026, 45th commit

## 🚦 Workflow Triggers

| Trigger | Action | Result |
|---------|--------|--------|
| Push to `main` | Auto | Build + Release |
| Push to `develop` | Auto | Build only |
| Pull Request | Auto | Build only |
| Manual Dispatch | Manual | Build + Optional Release |

## 📦 Artifacts

### Build Artifacts (30-day retention):
- `sports-betting-analyzer-android` folder containing APK

### GitHub Releases:
- Permanent storage
- Versioned releases
- Release notes with build info
- Direct APK download links

## 🔍 Troubleshooting

### Common Issues:

1. **Build Fails on Windows Runner**:
   - Ensure MAUI workloads are installed
   - Check .NET version compatibility

2. **Signing Errors**:
   - Verify keystore passwords in GitHub secrets
   - Ensure keystore alias matches workflow

3. **Version Conflicts**:
   - Check that version format is valid (x.y.z)
   - Ensure Android version code is integer

4. **Upload Failures**:
   - Check file paths in workflow
   - Verify APK was actually built

### Debug Commands:

```bash
# Local build test
dotnet publish mobile/SportsBettingAnalyzer.Mobile.csproj -c Release -f net9.0-android

# Check keystore info
keytool -list -v -keystore keystore.keystore
```

## 📱 Distribution Options

### GitHub Releases (Free):
- ✅ Automatic versioning
- ✅ Release notes
- ✅ Direct downloads
- ❌ Limited discoverability

### Google Play Store (Paid):
- ✅ Wide distribution
- ✅ Automatic updates
- ✅ Beta testing
- ✅ Analytics
- ❌ Developer account fee ($25)
- ❌ Review process

### Alternative Stores:
- **Amazon Appstore**
- **F-Droid** (for open source)
- **APKPure**
- **Direct hosting**

## 🎯 Best Practices

1. **Version Management**:
   - Use semantic versioning
   - Maintain changelog
   - Tag releases properly

2. **Security**:
   - Never commit keystore to git
   - Use strong passwords
   - Rotate secrets regularly

3. **Testing**:
   - Test APK before release
   - Use beta releases
   - Monitor crash reports

4. **Documentation**:
   - Update release notes
   - Document breaking changes
   - Provide installation guides

## 🚀 Next Steps

1. **Set up GitHub secrets**
2. **Create Android keystore**
3. **Test workflow on develop branch**
4. **Deploy to production from main branch**
5. **Consider Google Play Store for wider distribution**

## 📞 Support

If you encounter issues:
1. Check the Actions tab for build logs
2. Verify all secrets are correctly set
3. Ensure keystore is properly configured
4. Review Android signing requirements

For additional help, create an issue in the repository with:
- Build logs
- Workflow run ID
- Error messages
- Steps to reproduce
