#!/usr/bin/env Rscript
# NFL Season Simulator using nflseedR 2.0
# Uses nfl_simulations() - the new recommended API

# Parse arguments first
args <- commandArgs(trailingOnly = TRUE)
n_simulations <- ifelse(length(args) >= 1, as.integer(args[1]), 100)
output_file <- ifelse(length(args) >= 2, args[2], "/app/data/nfl/season_simulation.json")

cat(sprintf("Starting NFL simulation with %d iterations...\n", n_simulations))

# Install/load packages with error handling
tryCatch({
  if (!require("nflseedR", quietly = TRUE)) {
    cat("Installing nflseedR...\n")
    install.packages("nflseedR", repos = "https://cloud.r-project.org", quiet = TRUE)
  }
  library(nflseedR)
  
  if (!require("jsonlite", quietly = TRUE)) {
    cat("Installing jsonlite...\n")
    install.packages("jsonlite", repos = "https://cloud.r-project.org", quiet = TRUE)
  }
  library(jsonlite)
  
  if (!require("dplyr", quietly = TRUE)) {
    cat("Installing dplyr...\n")
    install.packages("dplyr", repos = "https://cloud.r-project.org", quiet = TRUE)
  }
  library(dplyr, warn.conflicts = FALSE)
  
}, error = function(e) {
  cat(sprintf("Package install error: %s\n", e$message))
  quit(status = 1)
})

cat("Packages loaded successfully\n")

# Determine current NFL season dynamically
current_date <- Sys.Date()
current_year <- as.integer(format(current_date, "%Y"))
current_month <- as.integer(format(current_date, "%m"))
nfl_season <- ifelse(current_month < 9, current_year - 1, current_year)

cat(sprintf("Simulating %d NFL season...\n", nfl_season))

# Run simulation using nflseedR 2.0 API
tryCatch({
  cat("Loading schedule data...\n")
  
  # Load current season games using nflseedR's built-in function
  games <- nflseedR::load_sharpe_games() |>
    dplyr::filter(season == nfl_season)
  
  cat(sprintf("Loaded %d games for %d season\n", nrow(games), nfl_season))
  
  # Determine chunks based on simulation count
  chunks <- max(2, min(10, n_simulations %/% 100))
  
  cat(sprintf("Running %d simulations in %d chunks...\n", n_simulations, chunks))
  
  # Use new nfl_simulations() API
  sim_results <- nflseedR::nfl_simulations(
    games = games,
    simulations = n_simulations,
    chunks = chunks
  )
  
  cat("Simulation complete, processing results...\n")
  
  # Extract overall standings (aggregated across all simulations)
  overall <- as.data.frame(sim_results$overall)
  
  cat(sprintf("Available columns: %s\n", paste(names(overall), collapse = ", ")))
  
  # Helper function to safely get column
  get_col <- function(df, col, default = 0) {
    if (col %in% names(df)) df[[col]] else rep(default, nrow(df))
  }
  
  # Build output for each conference
  build_team_list <- function(df, conf_name) {
    conf_df <- df[df$conf == conf_name, ]
    conf_df <- conf_df[order(-get_col(conf_df, "playoff", 0)), ]
    
    lapply(1:nrow(conf_df), function(i) {
      list(
        team = conf_df$team[i],
        conf = conf_name,
        division = conf_df$division[i],
        wins = round(get_col(conf_df, "wins", 0)[i], 1),
        playoff_pct = round(get_col(conf_df, "playoff", 0)[i] * 100, 1),
        division_pct = round(get_col(conf_df, "div1", 0)[i] * 100, 1),
        conf_pct = round(get_col(conf_df, "won_conf", 0)[i] * 100, 1),
        super_bowl_pct = round(get_col(conf_df, "won_sb", 0)[i] * 100, 1)
      )
    })
  }
  
  afc_teams <- build_team_list(overall, "AFC")
  nfc_teams <- build_team_list(overall, "NFC")
  all_teams <- c(afc_teams, nfc_teams)
  
  # Sort by Super Bowl probability
  sb_pcts <- sapply(all_teams, function(x) x$super_bowl_pct)
  all_teams <- all_teams[order(-sb_pcts)]
  
  output <- list(
    simulations = n_simulations,
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"),
    season = nfl_season,
    model = "nflseedR Elo",
    afc = afc_teams,
    nfc = nfc_teams,
    all_teams = all_teams,
    error = FALSE
  )
  
  # Write JSON output
  cat(sprintf("Writing results to %s...\n", output_file))
  dir.create(dirname(output_file), showWarnings = FALSE, recursive = TRUE)
  write(toJSON(output, auto_unbox = TRUE, pretty = TRUE), output_file)
  
  cat("Success!\n")
  
}, error = function(e) {
  cat(sprintf("Simulation error: %s\n", e$message))
  
  # Write error JSON
  error_output <- list(
    error = TRUE,
    message = e$message,
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S")
  )
  dir.create(dirname(output_file), showWarnings = FALSE, recursive = TRUE)
  write(toJSON(error_output, auto_unbox = TRUE), output_file)
  
  quit(status = 1)
})
