using System.Text.RegularExpressions;
using Tesseract;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class BetSlipOCRService
    {
        private readonly ILogger<BetSlipOCRService> _logger;
        private readonly string _tessDataPath;

        public BetSlipOCRService(ILogger<BetSlipOCRService> logger, IConfiguration configuration)
        {
            _logger = logger;
            _tessDataPath = configuration["Tesseract:DataPath"] ?? Path.Combine(Directory.GetCurrentDirectory(), "tessdata");
        }

        public async Task<BetSlip> ExtractBetSlipFromImageAsync(Stream imageStream)
        {
            try
            {
                // Convert stream to byte array
                using var memoryStream = new MemoryStream();
                await imageStream.CopyToAsync(memoryStream);
                var imageBytes = memoryStream.ToArray();

                // Perform OCR
                var extractedText = await PerformOCRAsync(imageBytes);

                if (string.IsNullOrWhiteSpace(extractedText))
                {
                    _logger.LogWarning("OCR extracted no text from image");
                    return new BetSlip { RawText = "No text extracted" };
                }

                _logger.LogInformation("OCR extracted text: {Text}", extractedText);

                // Parse the extracted text
                var betSlip = ParseBetSlipText(extractedText);
                betSlip.RawText = extractedText;

                return betSlip;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error extracting bet slip from image");
                throw;
            }
        }

        private async Task<string> PerformOCRAsync(byte[] imageBytes)
        {
            try
            {
                using var originalImg = Pix.LoadFromMemory(imageBytes);
                
                // Try multiple preprocessing strategies and OCR configurations
                var allResults = new List<(string Text, float Confidence, int Length)>();
                
                // Strategy 1: Original image with different PSM modes
                allResults.AddRange(await TryOCRWithModes(originalImg, "Original"));
                
                // Strategy 2: Scaled up image (better for small text)
                var scaledUp = ScaleImage(originalImg, 2.0f);
                allResults.AddRange(await TryOCRWithModes(scaledUp, "Scaled 2x"));
                scaledUp.Dispose();
                
                // Strategy 3: High contrast version
                var highContrast = EnhanceContrast(originalImg);
                allResults.AddRange(await TryOCRWithModes(highContrast, "High Contrast"));
                highContrast.Dispose();
                
                // Strategy 4: Grayscale with noise reduction
                var cleaned = CleanImage(originalImg);
                allResults.AddRange(await TryOCRWithModes(cleaned, "Cleaned"));
                cleaned.Dispose();
                
                // Strategy 5: Scaled + High Contrast combination
                var scaledContrast = ScaleImage(originalImg, 1.5f);
                var scaledContrastEnhanced = EnhanceContrast(scaledContrast);
                allResults.AddRange(await TryOCRWithModes(scaledContrastEnhanced, "Scaled+Contrast"));
                scaledContrast.Dispose();
                scaledContrastEnhanced.Dispose();
                
                // Select best result based on length and confidence
                var bestResult = allResults
                    .Where(r => r.Length > 50) // Minimum text length
                    .OrderByDescending(r => r.Confidence * r.Length) // Weighted score
                    .FirstOrDefault();
                
                if (bestResult.Text != null)
                {
                    _logger.LogInformation("Best OCR result: {Strategy}, Confidence: {Confidence}, Length: {Length}", 
                        bestResult.Text, bestResult.Confidence, bestResult.Length);
                    
                    // Post-process text to fix common OCR errors
                    return PostProcessText(bestResult.Text);
                }
                
                // Fallback: return longest result
                var fallback = allResults.OrderByDescending(r => r.Length).FirstOrDefault();
                return fallback.Text ?? string.Empty;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "OCR processing failed");
                throw new Exception("Failed to process image with OCR", ex);
            }
        }

        private Task<List<(string Text, float Confidence, int Length)>> TryOCRWithModes(Pix img, string strategyName)
        {
            var results = new List<(string Text, float Confidence, int Length)>();
            
            try
            {
                using var engine = new TesseractEngine(_tessDataPath, "eng", EngineMode.Default);
                
                // Configure OCR for better accuracy
                engine.SetVariable("tessedit_char_whitelist", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$.,:()@/ ");
                engine.SetVariable("tessedit_pageseg_mode", "6"); // Assume uniform block of text
                
                // Try different page segmentation modes
                var modes = new[] 
                { 
                    PageSegMode.Auto,
                    PageSegMode.SingleBlock,
                    PageSegMode.SingleColumn,
                    PageSegMode.SingleBlockVertText
                };
                
                foreach (var mode in modes)
                {
                    try
                    {
                        engine.DefaultPageSegMode = mode;
                        using var page = engine.Process(img);
                        var text = page.GetText().Trim();
                        
                        if (!string.IsNullOrWhiteSpace(text) && text.Length > 10)
                        {
                            var meanConfidence = page.GetMeanConfidence();
                            results.Add((text, meanConfidence, text.Length));
                            _logger.LogDebug("OCR {Strategy} PSM {Mode}: {Length} chars, {Confidence}% confidence", 
                                strategyName, mode, text.Length, meanConfidence);
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.LogDebug(ex, "OCR failed for {Strategy} with PSM {Mode}", strategyName, mode);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to create OCR engine for {Strategy}", strategyName);
            }
            
            return Task.FromResult(results);
        }

        private Pix ScaleImage(Pix img, float scaleFactor)
        {
            try
            {
                // Scale image up for better OCR on small text
                var newWidth = (int)(img.Width * scaleFactor);
                var newHeight = (int)(img.Height * scaleFactor);
                
                // Try to use Scale method if available
                try
                {
                    return img.Scale(newWidth, newHeight);
                }
                catch
                {
                    // If Scale method doesn't exist, return original
                    // Tesseract will handle the image as-is
                    _logger.LogDebug("Image scaling not available, using original");
                    return img;
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Failed to scale image");
                return img;
            }
        }

        private Pix EnhanceContrast(Pix img)
        {
            try
            {
                // Convert to grayscale if needed
                Pix processed = img;
                if (img.Depth > 1)
                {
                    try
                    {
                        processed = img.ConvertRGBToGray();
                    }
                    catch
                    {
                        // If conversion not available, use original
                        _logger.LogDebug("Grayscale conversion not available");
                        processed = img;
                    }
                }
                
                // Note: Advanced contrast enhancement would require additional image processing libraries
                // Tesseract handles basic preprocessing internally
                return processed;
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Failed to enhance contrast");
                return img;
            }
        }

        private Pix CleanImage(Pix img)
        {
            try
            {
                // Convert to grayscale for better OCR
                Pix processed = img;
                if (img.Depth > 1)
                {
                    try
                    {
                        processed = img.ConvertRGBToGray();
                    }
                    catch
                    {
                        _logger.LogDebug("Grayscale conversion not available");
                        processed = img;
                    }
                }
                
                // Basic cleaning - Tesseract handles most noise reduction internally
                return processed;
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Failed to clean image");
                return img;
            }
        }

        private string PostProcessText(string text)
        {
            if (string.IsNullOrWhiteSpace(text))
                return text;
            
            var processed = text;
            
            // Fix spacing issues first
            processed = Regex.Replace(processed, @"\s+", " "); // Multiple spaces to single
            processed = Regex.Replace(processed, @"\n\s*\n+", "\n"); // Multiple newlines to single
            
            // Fix common OCR mistakes in betting context - odds
            processed = Regex.Replace(processed, @"([+-])\s*(\d)", "$1$2"); // Fix "+ 594" -> "+594"
            processed = Regex.Replace(processed, @"(\d)\s*([+-])", "$1$2"); // Fix "594 +" -> "594+"
            
            // Fix dollar amounts
            processed = Regex.Replace(processed, @"\$\s*(\d)", "$$1"); // Fix "$ 5" -> "$5"
            processed = Regex.Replace(processed, @"(\d)\s*\$", "$1"); // Fix "5 $" -> "5"
            
            // Fix team name separators - ensure proper spacing around @
            processed = Regex.Replace(processed, @"(\w+)\s*@\s*(\w+)", "$1 @ $2");
            
            // Fix common character misrecognitions in numeric contexts
            // Only replace when it's clearly a number (surrounded by digits or symbols)
            // Note: Using alternation and escaping hyphen to avoid range issues
            processed = Regex.Replace(processed, @"([+\-$])\s*(O|o|I|i|l|L|S|s|Z|z)\s*(\d)", 
                m => m.Groups[1].Value + "0" + m.Groups[3].Value, RegexOptions.IgnoreCase); // Fix "+O594" -> "+0594" (but this is rare)
            
            // Fix common word OCR errors in betting context
            var wordFixes = new Dictionary<string, string>
            {
                { @"\bPARLAY\b", "PARLAY" },
                { @"\bSGP\b", "SGP" },
                { @"\bWAGER\b", "WAGER" },
                { @"\bTO WIN\b", "TO WIN" },
                { @"\bSELECTION\b", "SELECTION" },
                { @"\bTOUCHDOWN\b", "TOUCHDOWN" },
                { @"\bRUSHING\b", "RUSHING" },
                { @"\bRECEIVING\b", "RECEIVING" },
                { @"\bPASSING\b", "PASSING" },
            };
            
            // Preserve important betting terms (case-insensitive)
            foreach (var fix in wordFixes)
            {
                processed = Regex.Replace(processed, fix.Key, fix.Value, RegexOptions.IgnoreCase);
            }
            
            // Fix numbers that might have been misread
            // Common: 0/O, 1/I/l, 5/S, 2/Z
            // Only fix in contexts that are clearly numeric (odds, amounts)
            // Use alternation and escape hyphen to avoid character class range issues
            processed = Regex.Replace(processed, @"([+\-$])\s*(O|o|I|i|l|L|S|s|Z|z)(\d)", 
                m => {
                    var prefix = m.Groups[1].Value;
                    var charToFix = m.Groups[2].Value;
                    var rest = m.Groups[3].Value;
                    var replacement = charToFix.ToUpper() switch
                    {
                        "O" => "0",
                        "I" or "L" => "1",
                        "S" => "5",
                        "Z" => "2",
                        _ => charToFix
                    };
                    return prefix + replacement + rest;
                });
            
            // Clean up invalid characters but preserve betting-specific ones
            processed = Regex.Replace(processed, @"[^\w\s\+\-\$\.\,\:\@\(\)\/]", " ");
            
            // Final cleanup of spaces
            processed = Regex.Replace(processed, @"\s+", " ");
            processed = Regex.Replace(processed, @"\n\s+", "\n");
            
            return processed.Trim();
        }

        private BetSlip ParseBetSlipText(string text)
        {
            var betSlip = new BetSlip();
            var upperText = text.ToUpper();
            var lines = text.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(l => l.Trim())
                .Where(l => l.Length > 0)
                .ToList();

            _logger.LogInformation("Parsing {LineCount} lines of text", lines.Count);

            // Detect if it's a parlay
            if (upperText.Contains("PARLAY") || upperText.Contains("SGP") || upperText.Contains("SAME GAME PARLAY"))
            {
                betSlip.IsParlay = true;
                betSlip.BetType = "Parlay";
                
                // Extract parlay leg count
                var legPattern = @"(\d+)\s*(?:LEG|SELECTION)";
                var legMatch = Regex.Match(upperText, legPattern, RegexOptions.IgnoreCase);
                if (legMatch.Success && int.TryParse(legMatch.Groups[1].Value, out var legCount))
                {
                    betSlip.ParlayLegs = legCount;
                }
                else
                {
                    // Try to count selections
                    var selectionCount = Regex.Matches(upperText, @"SELECTION", RegexOptions.IgnoreCase).Count;
                    if (selectionCount > 0)
                    {
                        betSlip.ParlayLegs = selectionCount;
                    }
                }

                // Parse parlay selections
                betSlip.ParlaySelections = ParseParlaySelections(lines, upperText);
            }

            // Extract game info (e.g., "Philadelphia Eagles @ Green Bay Packers")
            var gameInfoPattern = @"([A-Z][A-Za-z\s]+)\s*@\s*([A-Z][A-Za-z\s]+)";
            var gameMatch = Regex.Match(text, gameInfoPattern);
            if (gameMatch.Success)
            {
                betSlip.GameInfo = gameMatch.Value.Trim();
                betSlip.Team1 = gameMatch.Groups[1].Value.Trim();
                betSlip.Team2 = gameMatch.Groups[2].Value.Trim();
            }

            // Extract odds (American format: +594, +150, -200, etc.)
            // Look for odds patterns, prioritizing larger numbers (parlay odds are usually higher)
            var americanOddsPattern = @"\+(\d{3,4})\b";
            var americanOddsMatches = Regex.Matches(text, americanOddsPattern);
            if (americanOddsMatches.Count > 0)
            {
                // For parlays, use the largest odds value (usually the parlay odds)
                var oddsValues = americanOddsMatches
                    .Cast<Match>()
                    .Select(m => decimal.TryParse(m.Groups[1].Value, out var val) ? val : 0m)
                    .Where(v => v > 0)
                    .OrderByDescending(v => v)
                    .ToList();
                
                if (oddsValues.Any())
                {
                    betSlip.Odds = oddsValues.First();
                    betSlip.OddsFormat = "American";
                }
            }
            else
            {
                // Try negative odds
                var negOddsPattern = @"-(\d{3,4})\b";
                var negMatch = Regex.Match(text, negOddsPattern);
                if (negMatch.Success && decimal.TryParse(negMatch.Groups[1].Value, out var negOdds))
                {
                    betSlip.Odds = -negOdds;
                    betSlip.OddsFormat = "American";
                }
            }

            // Extract wager amount - look for "WAGER", "Place $X bet", "$X.XX" patterns
            var wagerPatterns = new[]
            {
                @"WAGER[:\s]*\$(\d+(?:\.\d{2})?)",
                @"PLACE\s+\$(\d+(?:\.\d{2})?)\s+BET",
                @"\$(\d+(?:\.\d{2})?)\s*(?:BONUS|BET|WAGER)"
            };

            foreach (var pattern in wagerPatterns)
            {
                var wagerMatch = Regex.Match(upperText, pattern);
                if (wagerMatch.Success && decimal.TryParse(wagerMatch.Groups[1].Value, out var wager))
                {
                    betSlip.WagerAmount = wager;
                    break;
                }
            }

            // If no wager found, try simple $ pattern
            if (betSlip.WagerAmount == 0)
            {
                var simpleWagerPattern = @"\$(\d+\.\d{2})\b";
                var simpleMatch = Regex.Match(text, simpleWagerPattern);
                if (simpleMatch.Success && decimal.TryParse(simpleMatch.Groups[1].Value, out var wager))
                {
                    betSlip.WagerAmount = wager;
                }
            }

            // Extract potential win amount ("TO WIN: $29.71")
            var winPatterns = new[]
            {
                @"TO\s+WIN[:\s]*\$(\d+(?:\.\d{2})?)",
                @"WIN[:\s]*\$(\d+(?:\.\d{2})?)"
            };

            foreach (var pattern in winPatterns)
            {
                var winMatch = Regex.Match(upperText, pattern);
                if (winMatch.Success && decimal.TryParse(winMatch.Groups[1].Value, out var win))
                {
                    betSlip.PotentialWin = win;
                    break;
                }
            }

            // Detect sport from team names or context
            if (string.IsNullOrEmpty(betSlip.Sport) || betSlip.Sport == "Unknown")
            {
                var sportKeywords = new Dictionary<string, string>
                {
                    { "EAGLES|PACKERS|CHIEFS|BILLS|NFL|FOOTBALL", "NFL" },
                    { "LAKERS|WARRIORS|CELTICS|NBA|BASKETBALL", "NBA" },
                    { "YANKEES|DODGERS|MLB|BASEBALL", "MLB" },
                    { "BRUINS|RANGERS|NHL|HOCKEY", "NHL" },
                    { "NASCAR|DAYTONA|TALLADEGA|SPEEDWAY", "NASCAR" }
                };

                foreach (var kvp in sportKeywords)
                {
                    if (Regex.IsMatch(upperText, kvp.Key))
                    {
                        betSlip.Sport = kvp.Value;
                        break;
                    }
                }
            }

            // Extract time/date if available
            var timePattern = @"(\d{1,2}:\d{2}(?:AM|PM)?)\s*(?:CT|ET|PT|MT)";
            var timeMatch = Regex.Match(text, timePattern, RegexOptions.IgnoreCase);
            if (timeMatch.Success)
            {
                // Store time info in GameInfo if not already set
                if (string.IsNullOrEmpty(betSlip.GameInfo))
                {
                    betSlip.GameInfo = timeMatch.Value;
                }
            }

            return betSlip;
        }

        private List<ParlayLeg> ParseParlaySelections(List<string> lines, string upperText)
        {
            var selections = new List<ParlayLeg>();
            
            // Look for player names followed by bet descriptions
            // Pattern: Player name, then bet type like "ANY TIME TOUCHDOWN SCORER"
            var playerNamePattern = @"([A-Z][a-z]+\s+[A-Z][a-z]+)"; // First Last name pattern
            
            // Common bet type patterns
            var betTypePatterns = new[]
            {
                @"ANY\s+TIME\s+TOUCHDOWN\s+SCORER",
                @"ALT\s+RUSHING\s+YDS",
                @"ALT\s+RECEIVING\s+YDS",
                @"ALT\s+PASSING\s+YDS",
                @"OVER|UNDER",
                @"TOUCHDOWN",
                @"RECEPTIONS",
                @"RUSHING\s+YARDS",
                @"RECEIVING\s+YARDS"
            };

            // Look for lines containing player names and bet types
            foreach (var line in lines)
            {
                var upperLine = line.ToUpper();
                
                // Check if line contains a player name pattern
                var nameMatch = Regex.Match(line, playerNamePattern);
                if (!nameMatch.Success) continue;

                var playerName = nameMatch.Value;
                var leg = new ParlayLeg { PlayerName = playerName };

                // Check for bet type
                foreach (var pattern in betTypePatterns)
                {
                    if (Regex.IsMatch(upperLine, pattern))
                    {
                        leg.BetDescription = Regex.Match(upperLine, pattern).Value;
                        break;
                    }
                }

                // Look for stat values (e.g., "50+", "25+")
                var statPattern = @"(\d+)\s*\+";
                var statMatch = Regex.Match(line, statPattern);
                if (statMatch.Success && decimal.TryParse(statMatch.Groups[1].Value, out var statValue))
                {
                    leg.StatValue = statValue;
                    leg.StatOperator = "+";
                    
                    // Determine stat type from context
                    if (upperLine.Contains("RUSHING") || upperLine.Contains("RUSH"))
                    {
                        leg.StatType = "RUSHING YARDS";
                    }
                    else if (upperLine.Contains("RECEIVING") || upperLine.Contains("REC"))
                    {
                        leg.StatType = "RECEIVING YARDS";
                    }
                    else if (upperLine.Contains("PASSING") || upperLine.Contains("PASS"))
                    {
                        leg.StatType = "PASSING YARDS";
                    }
                }

                // If we found a player and some bet info, add it
                if (!string.IsNullOrEmpty(leg.PlayerName) && 
                    (!string.IsNullOrEmpty(leg.BetDescription) || leg.StatValue.HasValue))
                {
                    selections.Add(leg);
                }
            }

            _logger.LogInformation("Parsed {Count} parlay selections", selections.Count);
            return selections;
        }
    }
}


