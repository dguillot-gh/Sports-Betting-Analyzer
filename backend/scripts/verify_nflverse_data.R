tryCatch({
  if (!require("readr", quietly = TRUE)) install.packages("readr", quiet = TRUE)
  if (!require("dplyr", quietly = TRUE)) install.packages("dplyr", quiet = TRUE)
  
  # Define paths (Docker vs Local)
  paths_to_check <- c(
    "/app/data/nflverse/schedules.csv",
    "../../data/nflverse/schedules.csv",
    "C:/Users/dguil/source/repos/PythonMLService/backend/data/nflverse/schedules.csv"
  )
  
  schedules_path <- NULL
  for (p in paths_to_check) {
    if (file.exists(p)) {
      schedules_path <- p
      break
    }
  }
  
  if (is.null(schedules_path)) {
    cat("❌ schedules.csv NOT found in expected locations.\n")
    quit(status = 1)
  }
  
  cat(sprintf("✅ Found file at: %s\n", schedules_path))
  
  # Load data
  library(readr)
  library(dplyr)
  
  games <- read_csv(schedules_path, show_col_types = FALSE)
  cat(sprintf("✅ Successfully loaded %d games.\n", nrow(games)))
  
  # Check schema for nflseedR 2.0 compatibility
  # Required columns for nfl_simulations()
  required_cols <- c("season", "game_type", "week", "away_team", "home_team", "result")
  missing_cols <- setdiff(required_cols, names(games))
  
  if (length(missing_cols) > 0) {
    cat(sprintf("❌ Schema mismatch! Missing columns: %s\n", paste(missing_cols, collapse = ", ")))
    quit(status = 1)
  }
  
  cat("✅ Schema check PASSED! Columns present: season, game_type, week, away_team, home_team, result.\n")
  
  # Check recent data
  max_season <- max(games$season, na.rm = TRUE)
  cat(sprintf("✅ Data freshness check: Latest season in file is %d.\n", max_season))
  
  if (max_season < 2024) {
    cat("⚠️ Warning: Data seems old (latest season < 2024).\n")
  }
  
  cat("SUCCESS: Data is valid and ready for nflseedR integration.\n")
  
}, error = function(e) {
  cat(sprintf("❌ Error running verification: %s\n", e$message))
  quit(status = 1)
})
