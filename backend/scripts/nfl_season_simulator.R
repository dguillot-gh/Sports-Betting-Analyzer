#!/usr/bin/env Rscript
# NFL Season Simulator using nflseedR
# Runs NFL season simulations and outputs playoff probabilities

# Suppress package loading messages
suppressPackageStartupMessages({
  if (!require("nflseedR", quietly = TRUE)) {
    install.packages("nflseedR", repos = "https://cloud.r-project.org", quiet = TRUE)
    library(nflseedR)
  }
  if (!require("jsonlite", quietly = TRUE)) {
    install.packages("jsonlite", repos = "https://cloud.r-project.org", quiet = TRUE)
    library(jsonlite)
  }
  if (!require("dplyr", quietly = TRUE)) {
    install.packages("dplyr", repos = "https://cloud.r-project.org", quiet = TRUE)
    library(dplyr, warn.conflicts = FALSE)
  }
})

# Parse command line arguments
args <- commandArgs(trailingOnly = TRUE)
n_simulations <- ifelse(length(args) >= 1, as.integer(args[1]), 1000)
output_file <- ifelse(length(args) >= 2, args[2], "nfl_sim_results.json")
# Toggle for custom ML model (can be passed as arg or env var)
use_ml_model <- Sys.getenv("USE_ML_MODEL", "FALSE") == "TRUE"

cat(sprintf("Running %d NFL season simulations (ML Model: %s)...\n", n_simulations, use_ml_model))

# 1. Load Local Data (Verified in Phase 1)
# ---------------------------------------------------------
schedules_path <- "/app/data/nflverse/schedules.csv"
if (!file.exists(schedules_path)) {
  schedules_path <- "data/nflverse/schedules.csv" # Fallback
}

if (file.exists(schedules_path)) {
  cat("Loading local schedules.csv...\n")
  games_df <- read.csv(schedules_path, stringsAsFactors = FALSE)
  
  # Filter for current season(s) required by nflseedR
  # nflseedR expects a 'sims_games' compatible dataframe
  # We use the loaded schedule as the base
} else {
  stop("Local schedules.csv not found! Run nfl_importer.py first.")
}

# 2. Define Custom Compute Function
# ---------------------------------------------------------
# This function will be called by nfl_simulations for every week
ml_compute_results <- function(teams, games, week_num, ...) {
  # Load required packages
  if (!requireNamespace("httr", quietly = TRUE)) return(nflseedR::nflseedR_compute_results(teams, games, week_num, ...))
  
  # Filter games for this week that need simulation (result is NA)
  week_games_indices <- which(games$week == week_num & is.na(games$result))
  
  if (length(week_games_indices) > 0) {
    # Print progress for UI tracking (captured by regex in backend/frontend)
    cat(sprintf("Simulating Week %d (%d games)...\n", week_num, length(week_games_indices)))
    
    for (i in week_games_indices) {
      home <- games$home_team[i]
      away <- games$away_team[i]
      
      # Prepare API call
      # Using tryCatch to prevent simulation crash on single game failure
      tryCatch({
        # We assume backend is reachable at 'backend' hostname in docker-compose
        # Or 'localhost' if running natively (fallback logic would be complex in R, assuming Docker)
        base_url <- "http://backend:8000/odds/nfl/predict"
        
        # NOTE: Using 'test=' param or similar might be good to avoid spamming logs, 
        # but for now we just call the predictor.
        
        resp <- httr::POST(
          url = base_url,
          query = list(
            home_team = home,
            away_team = away
          ),
          timeout(2) # Short timeout to keep simulations moving
        )
        
        if (httr::status_code(resp) == 200) {
          data <- httr::content(resp, as = "parsed")
          
          # Extract Win Probability
          win_prob <- data$home_win_probability
          
          # Convert Win Probability to Point Differential (Result)
          # Simple approximation: Margin = (WinProb - 0.5) * 25
          # e.g. 50% -> 0, 90% -> +10, 10% -> -10
          # We add some randomness to make simulations varied!
          # Otherwise every run is identical for the same teams.
          
          margin_pred <- (win_prob - 0.5) * 25
          
          # Add randomness: Variance of ~12-14 points (NFL std dev)
          sim_margin <- margin_pred + rnorm(1, mean = 0, sd = 13)
          
          # Round to integer
          games$result[i] <- round(sim_margin)
          
        } else {
          # Fallback to random if API fails
          games$result[i] <- round(rnorm(1, mean = 0, sd = 13))
        }
        
      }, error = function(e) {
        # Fallback on error
        games$result[i] <- round(rnorm(1, mean = 0, sd = 13))
      })
    }
  }
  
  # Return updated structures
  list(teams = teams, games = games)
}

# 3. Run Simulation
# ---------------------------------------------------------
tryCatch({
  
  # Use nfl_simulations (2.0 API)
  cat("Starting nfl_simulations()...\n")
  
  sim_results <- nflseedR::nfl_simulations(
    games = games_df,
    simulations = n_simulations,
    compute_results = if(use_ml_model) ml_compute_results else nflseedR::nflseedR_compute_results,
    exec = "multiprocess" # Parallel execution if available
  )
  
  # Extract standings/overall results
  # nfl_simulations returns a list of dataframes (overall, team_stats, game_stats)
  final <- sim_results$overall
  
  # Map columns for UI consistency (same as previous)
  # nflseedR 2.0 columns might slightly differ, ensuring mapping:
  cols_map <- c(
    "conf" = "conf", 
    "division" = "division",
    "wins" = "wins",
    "losses" = "losses",
    "playoff" = "playoff_pct", # renamed
    "div_win" = "division_pct",
    "conf_champ" = "conf_pct",
    "sb_champ" = "super_bowl_pct"
  )
  
  # Rename/Calculate percentages
  if ("playoff" %in% names(final)) final$playoff_pct <- round(final$playoff * 100, 1)
  if ("div_win" %in% names(final)) final$division_pct <- round(final$div_win * 100, 1)
  if ("conf_champ" %in% names(final)) final$conf_pct <- round(final$conf_champ * 100, 1)
  if ("sb_champ" %in% names(final)) final$super_bowl_pct <- round(final$sb_champ * 100, 1)
  
  # Group by conference
  final <- final %>% arrange(desc(super_bowl_pct))
  afc_teams <- final %>% filter(conf == "AFC")
  nfc_teams <- final %>% filter(conf == "NFC")
  
  # Helper for JSON output (Row-Oriented)
  df_to_rows <- function(df) {
    if (nrow(df) == 0) return(list())
    lapply(seq_len(nrow(df)), function(i) as.list(df[i, , drop = FALSE]))
  }
  
  output <- list(
    simulations = n_simulations,
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"),
    season = max(games_df$season, na.rm = TRUE),
    afc = df_to_rows(afc_teams),
    nfc = df_to_rows(nfc_teams),
    all_teams = df_to_rows(final)
  )
  
  write_json(output, output_file, auto_unbox = TRUE, pretty = TRUE)
  cat(sprintf("Success! Results written to %s\n", output_file))

}, error = function(e) {
  cat(sprintf("Error during simulation: %s\n", e$message))
  # Write error JSON
  write_json(list(error = TRUE, message = e$message), output_file, auto_unbox = TRUE)
  quit(status = 1)
})
