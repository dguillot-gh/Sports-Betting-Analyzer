#!/usr/bin/env Rscript
# NFL Season Simulator using nflseedR (Simplified Version)
# Uses nflseedR's built-in Elo engine for reliable simulations

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

# Run simulation using nflseedR's built-in function
tryCatch({
  cat("Running nflseedR simulation...\n")
  
  # Determine current NFL season dynamically
  # NFL season starts in September, so if we're before September, use previous year
  current_date <- Sys.Date()
  current_year <- as.integer(format(current_date, "%Y"))
  current_month <- as.integer(format(current_date, "%m"))
  
  # If before September, the current season is previous year
  # Otherwise, the current season is this year
  nfl_season <- ifelse(current_month < 9, current_year - 1, current_year)
  
  cat(sprintf("Simulating %d NFL season...\n", nfl_season))
  
  # Use nflseedR's simulate_nfl which fetches its own data
  sim_results <- simulate_nfl(
    nfl_season = nfl_season,
    fresh_season = TRUE,
    simulations = n_simulations,
    print_summary = FALSE
  )
  
  cat("Simulation complete, processing results...\n")
  
  # Extract overall standings
  standings <- sim_results$overall
  
  # Debug: print available columns
  cat(sprintf("Available columns: %s\n", paste(names(standings), collapse = ", ")))
  
  # Convert to data frame for simpler processing
  standings <- as.data.frame(standings)
  
  # Safely get column values with fallbacks
  get_col <- function(df, col, default = 0) {
    if (col %in% names(df)) df[[col]] else rep(default, nrow(df))
  }
  
  # Build simplified output for each team
  process_teams <- function(df, conference) {
    conf_teams <- df[df$conf == conference, ]
    conf_teams <- conf_teams[order(-get_col(conf_teams, "playoff", 0)), ]
    
    lapply(1:nrow(conf_teams), function(i) {
      list(
        team = conf_teams$team[i],
        conf = conference,
        division = conf_teams$division[i],
        wins = round(get_col(conf_teams, "wins", 0)[i], 1),
        playoff_pct = round(get_col(conf_teams, "playoff", 0)[i] * 100, 1),
        division_pct = round(get_col(conf_teams, "div1", get_col(conf_teams, "div_pct", 0))[i] * 100, 1),
        conf_pct = round(get_col(conf_teams, "conf", 0)[i] * 100, 1),
        super_bowl_pct = round(get_col(conf_teams, "sb_win", get_col(conf_teams, "won_sb", 0))[i] * 100, 1)
      )
    })
  }
  
  afc_teams <- process_teams(standings, "AFC")
  nfc_teams <- process_teams(standings, "NFC")
  all_teams <- c(afc_teams, nfc_teams)
  
  # Sort all_teams by super bowl pct
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
