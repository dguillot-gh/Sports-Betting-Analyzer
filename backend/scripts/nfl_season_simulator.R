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
  
  # Build output structure
  afc_teams <- standings %>% 
    filter(conf == "AFC") %>%
    arrange(desc(playoff)) %>%
    mutate(
      playoff_pct = round(playoff * 100, 1),
      division_pct = round(div1 * 100, 1),
      conf_pct = round(conf * 100, 1),
      super_bowl_pct = round(sb_win * 100, 1)
    ) %>%
    select(team, conf, division, wins, playoff_pct, division_pct, conf_pct, super_bowl_pct)
  
  nfc_teams <- standings %>%
    filter(conf == "NFC") %>%
    arrange(desc(playoff)) %>%
    mutate(
      playoff_pct = round(playoff * 100, 1),
      division_pct = round(div1 * 100, 1),
      conf_pct = round(conf * 100, 1),
      super_bowl_pct = round(sb_win * 100, 1)
    ) %>%
    select(team, conf, division, wins, playoff_pct, division_pct, conf_pct, super_bowl_pct)
  
  all_teams <- bind_rows(afc_teams, nfc_teams) %>%
    arrange(desc(super_bowl_pct))
  
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
