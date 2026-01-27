#!/usr/bin/env Rscript
# College Baseball Importer using baseballr
# Fetches NCAA baseball data: teams, player stats, schedules

# Parse command line arguments
args <- commandArgs(trailingOnly = TRUE)
division <- ifelse(length(args) >= 1, as.integer(args[1]), 1)
year <- ifelse(length(args) >= 2, as.integer(args[2]), as.integer(format(Sys.Date(), "%Y")))
output_dir <- ifelse(length(args) >= 3, args[3], "/app/data/baseball")
team_id <- ifelse(length(args) >= 4, as.integer(args[4]), NA)  # Optional: import specific team only

cat(sprintf("College Baseball Importer - Division %d, Year %d\n", division, year))
cat(sprintf("Output directory: %s\n", output_dir))

# Install/load packages
tryCatch({
  # Install remotes for GitHub packages
  if (!require("remotes", quietly = TRUE)) {
    install.packages("remotes", repos = "https://cloud.r-project.org", quiet = TRUE)
  }

  if (!require("baseballr", quietly = TRUE)) {
    cat("Installing baseballr (from GitHub)...\n")
    tryCatch({
        remotes::install_github("BillPetti/baseballr", upgrade = "never", quiet = TRUE)
    }, error = function(e) {
        cat(sprintf("GitHub install failed (%s). Falling back to CRAN...\n", e$message))
        install.packages("baseballr", repos = "https://cloud.r-project.org", quiet = TRUE)
    })
  }
  library(baseballr)
  
  if (!require("jsonlite", quietly = TRUE)) {
    install.packages("jsonlite", repos = "https://cloud.r-project.org", quiet = TRUE)
  }
  library(jsonlite)
  
  if (!require("dplyr", quietly = TRUE)) {
    install.packages("dplyr", repos = "https://cloud.r-project.org", quiet = TRUE)
  }
  library(dplyr, warn.conflicts = FALSE)
  
}, error = function(e) {
  cat(sprintf("Package install error: %s\n", e$message))
  quit(status = 1)
})

cat("Packages loaded successfully\n")

# Create output directories
dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(output_dir, "stats"), showWarnings = FALSE)
dir.create(file.path(output_dir, "schedules"), showWarnings = FALSE)

# Helper function to safely fetch data
safe_fetch <- function(expr, description) {
  tryCatch({
    cat(sprintf("Fetching %s...\n", description))
    result <- expr
    cat(sprintf("  -> Got %d rows\n", nrow(result)))
    return(result)
  }, error = function(e) {
    cat(sprintf("  -> ERROR: %s\n", e$message))
    return(NULL)
  })
}

# 1. Fetch all teams for division
cat(sprintf("\n=== Fetching Division %d Teams ===\n", division))

teams <- tryCatch({
  cat(sprintf("Calling baseballr::ncaa_teams(division=%d, year=%d)...\n", division, year))
  result <- baseballr::ncaa_teams(division = division, year = year)
  cat(sprintf("  -> Got %d rows\n", if(!is.null(result)) nrow(result) else 0))
  result
}, error = function(e) {
  cat(sprintf("ERROR calling ncaa_teams: %s\n", e$message))
  cat("This could be due to:\n")
  cat("  1. NCAA website is down or blocking requests\n")
  cat("  2. Network connectivity issues\n")
  cat("  3. baseballr package needs updating\n")
  cat("  4. Invalid division/year combination\n")
  return(NULL)
})

if (is.null(teams) || nrow(teams) == 0) {
  cat(sprintf("ERROR: No teams found for Division %d, Year %d!\n", division, year))
  cat("Try a different year (e.g., 2024) or check network connectivity.\n")
  quit(status = 1)
}


# Save teams list
teams_file <- file.path(output_dir, sprintf("teams_d%d.json", division))
write(toJSON(teams, auto_unbox = TRUE, pretty = TRUE), teams_file)
cat(sprintf("Saved %d teams to %s\n", nrow(teams), teams_file))

# 2. If specific team requested, only import that team
if (!is.na(team_id)) {
  teams_to_import <- teams[teams$team_id == team_id, ]
  if (nrow(teams_to_import) == 0) {
    cat(sprintf("Team ID %d not found in division %d!\n", team_id, division))
    quit(status = 1)
  }
} else {
  # For full import, limit to first 50 teams to avoid rate limits
  # Users can import specific teams or conferences later
  teams_to_import <- head(teams, 50)
  cat(sprintf("Importing stats for first %d teams (use team_id arg for specific team)\n", nrow(teams_to_import)))
}

# 3. Import stats for each team
cat(sprintf("\n=== Importing Team Stats (%d teams) ===\n", nrow(teams_to_import)))

for (i in 1:nrow(teams_to_import)) {
  team <- teams_to_import[i, ]
  team_name <- team$team_name
  tid <- team$team_id
  
  cat(sprintf("\n[%d/%d] %s (ID: %d)\n", i, nrow(teams_to_import), team_name, tid))
  
  # Batting stats
  batting <- safe_fetch(
    baseballr::ncaa_team_player_stats(team_id = tid, year = year, type = "batting"),
    "batting stats"
  )
  if (!is.null(batting) && nrow(batting) > 0) {
    write.csv(batting, file.path(output_dir, "stats", sprintf("%d_batting.csv", tid)), row.names = FALSE)
  }
  
  # Pitching stats
  pitching <- safe_fetch(
    baseballr::ncaa_team_player_stats(team_id = tid, year = year, type = "pitching"),
    "pitching stats"
  )
  if (!is.null(pitching) && nrow(pitching) > 0) {
    write.csv(pitching, file.path(output_dir, "stats", sprintf("%d_pitching.csv", tid)), row.names = FALSE)
  }
  
  # Schedule/results
  schedule <- safe_fetch(
    baseballr::ncaa_schedule_info(team_id = tid, year = year),
    "schedule"
  )
  if (!is.null(schedule) && nrow(schedule) > 0) {
    write.csv(schedule, file.path(output_dir, "schedules", sprintf("%d_schedule.csv", tid)), row.names = FALSE)
  }
  
  # Small delay to avoid rate limiting
  Sys.sleep(0.5)
}

# 4. Create summary file
summary <- list(
  division = division,
  year = year,
  total_teams = nrow(teams),
  imported_teams = nrow(teams_to_import),
  generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S"),
  teams_imported = teams_to_import$team_name
)

summary_file <- file.path(output_dir, sprintf("import_summary_d%d.json", division))
write(toJSON(summary, auto_unbox = TRUE, pretty = TRUE), summary_file)

cat(sprintf("\n=== Import Complete ===\n"))
cat(sprintf("Division: %d\n", division))
cat(sprintf("Year: %d\n", year))
cat(sprintf("Teams imported: %d / %d\n", nrow(teams_to_import), nrow(teams)))
cat(sprintf("Summary saved to: %s\n", summary_file))
cat("Success!\n")
