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

cat(sprintf("Running %d NFL season simulations...\n", n_simulations))

# Get current year
current_year <- as.integer(format(Sys.Date(), "%Y"))
# If we're in Jan-Feb, use previous year's season
if (as.integer(format(Sys.Date(), "%m")) <= 2) {
  current_year <- current_year - 1
}

# Run simulations using nflseedR
tryCatch({
  # Try the newer simulate_nfl() function first (nflseedR 2.0+)
  sim_results <- NULL
  
  # Check which function is available
  if (exists("simulate_nfl", where = asNamespace("nflseedR"))) {
    cat("Using simulate_nfl() (nflseedR 2.0+)\n")
    sim_results <- simulate_nfl(
      nfl_season = current_year,
      simulations = n_simulations,
      fresh_season = FALSE
    )
  } else if (exists("nfl_simulations", where = asNamespace("nflseedR"))) {
    cat("Using nfl_simulations() (older nflseedR)\n")
    sim_results <- nfl_simulations(
      nfl_season = current_year,
      simulations = n_simulations,
      fresh_season = FALSE,
      verbosity = 0
    )
  } else {
    stop("No compatible simulation function found in nflseedR")
  }
  
  # Extract standings
  standings <- NULL
  if (!is.null(sim_results$standings)) {
    standings <- sim_results$standings
  } else if (!is.null(sim_results$overall)) {
    standings <- sim_results$overall
  }
  
  if (!is.null(standings) && nrow(standings) > 0) {
    # Process standings with available columns
    processed <- standings %>%
      arrange(team)
    
    # Map columns that might have different names
    if ("playoff" %in% names(processed)) {
      processed$playoff_pct <- round(processed$playoff * 100, 1)
    } else if ("make_playoffs" %in% names(processed)) {
      processed$playoff_pct <- round(processed$make_playoffs * 100, 1)
    } else {
      processed$playoff_pct <- 0
    }
    
    if ("div_win" %in% names(processed)) {
      processed$division_pct <- round(processed$div_win * 100, 1)
    } else if ("win_division" %in% names(processed)) {
      processed$division_pct <- round(processed$win_division * 100, 1)
    } else {
      processed$division_pct <- 0
    }
    
    if ("conf_champ" %in% names(processed)) {
      processed$conf_pct <- round(processed$conf_champ * 100, 1)
    } else if ("win_conference" %in% names(processed)) {
      processed$conf_pct <- round(processed$win_conference * 100, 1)
    } else {
      processed$conf_pct <- 0
    }
    
    if ("sb_champ" %in% names(processed)) {
      processed$super_bowl_pct <- round(processed$sb_champ * 100, 1)
    } else if ("win_sb" %in% names(processed)) {
      processed$super_bowl_pct <- round(processed$win_sb * 100, 1)
    } else {
      processed$super_bowl_pct <- 0
    }
    
    # Get wins/losses
    if (!"wins" %in% names(processed)) processed$wins <- 0
    if (!"losses" %in% names(processed)) processed$losses <- 0
    
    # Select final columns
    final <- processed %>%
      select(
        team,
        any_of(c("conf", "division")),
        wins,
        losses,
        playoff_pct,
        division_pct,
        conf_pct,
        super_bowl_pct
      )
    
    # Group by conference if available
    if ("conf" %in% names(final)) {
      afc_teams <- final %>% filter(conf == "AFC") %>% arrange(desc(playoff_pct))
      nfc_teams <- final %>% filter(conf == "NFC") %>% arrange(desc(playoff_pct))
    } else {
      afc_teams <- final[1:16,]
      nfc_teams <- final[17:32,]
    }
    
    # Create output structure
    output <- list(
      simulations = n_simulations,
      generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"),
      season = current_year,
      afc = as.list(afc_teams),
      nfc = as.list(nfc_teams),
      all_teams = as.list(final %>% arrange(desc(super_bowl_pct)))
    )
    
    # Write JSON output
    write_json(output, output_file, auto_unbox = TRUE, pretty = TRUE)
    cat(sprintf("Results written to %s\n", output_file))
    cat("NFL simulation complete!\n")
    
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
