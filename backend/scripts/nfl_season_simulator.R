#!/usr/bin/env Rscript
# NFL Season Simulator using nflseedR
# Runs NFL season simulations and outputs playoff probabilities

# Install packages if needed
if (!require("nflseedR")) install.packages("nflseedR", repos = "https://cloud.r-project.org")
if (!require("jsonlite")) install.packages("jsonlite", repos = "https://cloud.r-project.org")
if (!require("dplyr")) install.packages("dplyr", repos = "https://cloud.r-project.org")

library(nflseedR)
library(jsonlite)
library(dplyr)

# Parse command line arguments
args <- commandArgs(trailingOnly = TRUE)
n_simulations <- ifelse(length(args) >= 1, as.integer(args[1]), 1000)
output_file <- ifelse(length(args) >= 2, args[2], "nfl_sim_results.json")

cat(sprintf("Running %d NFL season simulations...\n", n_simulations))

# Run simulations using nflseedR 2.0
tryCatch({
  # Get current season standings to simulate from
  sim_results <- nfl_simulations(
    nfl_season = as.integer(format(Sys.Date(), "%Y")),
    simulations = n_simulations,
    fresh_season = FALSE,  # Use current standings
    verbosity = 1
  )
  
  # Extract overall standings with probabilities
  if (!is.null(sim_results$standings)) {
    standings <- sim_results$standings %>%
      arrange(team) %>%
      mutate(
        playoff_pct = round(playoff * 100, 1),
        division_pct = round(div_win * 100, 1),
        conf_pct = round(conf_champ * 100, 1),
        super_bowl_pct = round(sb_champ * 100, 1),
        first_pick_pct = round(pick1 * 100, 1)
      ) %>%
      select(
        team,
        conf,
        division,
        wins,
        losses,
        playoff_pct,
        division_pct,
        conf_pct,
        super_bowl_pct,
        first_pick_pct
      )
    
    # Group by conference
    afc_teams <- standings %>% filter(conf == "AFC") %>% arrange(desc(playoff_pct))
    nfc_teams <- standings %>% filter(conf == "NFC") %>% arrange(desc(playoff_pct))
    
    # Create output structure
    output <- list(
      simulations = n_simulations,
      generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"),
      season = as.integer(format(Sys.Date(), "%Y")),
      afc = as.list(afc_teams),
      nfc = as.list(nfc_teams),
      all_teams = as.list(standings %>% arrange(desc(super_bowl_pct)))
    )
    
    # Write JSON output
    write_json(output, output_file, auto_unbox = TRUE, pretty = TRUE)
    cat(sprintf("Results written to %s\n", output_file))
    
  } else {
    stop("No standings data returned from simulation")
  }
  
}, error = function(e) {
  # Create error output
  error_output <- list(
    error = TRUE,
    message = as.character(e),
    generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S")
  )
  write_json(error_output, output_file, auto_unbox = TRUE, pretty = TRUE)
  cat(sprintf("Error: %s\n", e$message))
  quit(status = 1)
})

cat("NFL simulation complete!\n")
