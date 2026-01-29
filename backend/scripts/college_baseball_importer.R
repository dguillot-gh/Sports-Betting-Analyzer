#!/usr/bin/env Rscript
# College Baseball Importer using baseballr
# Fetches NCAA baseball data: teams, player stats, schedules

# Parse command line arguments
args <- commandArgs(trailingOnly = TRUE)
division <- ifelse(length(args) >= 1, as.integer(args[1]), 1)
year <- ifelse(length(args) >= 2, as.integer(args[2]), as.integer(format(Sys.Date(), "%Y")))
output_dir <- ifelse(length(args) >= 3, args[3], "/app/data/baseball")
team_id_arg <- ifelse(length(args) >= 4, args[4], NA)
custom_id <- ifelse(length(args) >= 5, args[5], NA)

# Convert team_id_arg to numeric if possible
team_id <- as.integer(team_id_arg)
team_name_query <- if(is.na(team_id)) team_id_arg else NA

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
  
  if (!require("jsonlite", quietly = TRUE)) {
    install.packages("jsonlite", repos = "https://cloud.r-project.org", quiet = TRUE)
  }
  library(jsonlite)
  if (!require("httr", quietly = TRUE)) {
    install.packages("httr", repos = "https://cloud.r-project.org", quiet = TRUE)
  }
  library(httr)
  
  # Set global headers to bypass bot detection (403 Forbidden)
  ua <- "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
  options(HTTPUserAgent = ua)
  options(warn = -1) # Suppress "NAs introduced by coercion" and other non-critical noise
  httr::set_config(httr::add_headers(
    `User-Agent` = ua,
    `Accept` = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    `Accept-Language` = "en-US,en;q=0.9",
    `Referer` = "https://stats.ncaa.org/",
    `Connection` = "keep-alive",
    `Upgrade-Insecure-Requests` = "1",
    `Cache-Control` = "max-age=0"
  ))
  
  # Also set options for the underlying curl if possible
  options(download.file.extra = sprintf('--header "User-Agent: %s"', ua))
  
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
    # Add a small random jitter to avoid patterns
    Sys.sleep(runif(1, 0.5, 1.5))
    cat(sprintf("Fetching %s...\n", description))
    result <- expr
    cat(sprintf("  -> Got %d rows\n", if(!is.null(result)) nrow(result) else 0))
    return(result)
  }, error = function(e) {
    cat(sprintf("  -> ERROR: %s\n", e$message))
    return(NULL)
  })
}

# 1. Fetch all teams for division
cat(sprintf("\n=== Fetching Division %d Teams ===\n", division))

# Try to get a session cookie first
cat("Performing session handshake...\n")
handshake <- tryCatch({
  httr::GET("https://stats.ncaa.org/", httr::timeout(10))
}, error = function(e) return(NULL))

teams <- tryCatch({
  cat(sprintf("Calling ncaa_teams for year %d...\n", year))
  # Wrap in a 403-aware fetch if possible
  result <- baseballr::ncaa_teams(division = division, year = year)
  if (is.null(result) || nrow(result) == 0) {
      cat("  -> No data returned (might be 403 blocked)\n")
  } else {
      cat(sprintf("  -> Got %d rows\n", nrow(result)))
  }
  result
}, error = function(e) {
  if (grepl("403", e$message)) {
      cat("  -> ERROR: Access Denied (403). NCAA is blocking this request.\n")
  } else {
      cat(sprintf("ERROR: %s\n", e$message))
  }
  return(NULL)
})

# Automatic fallback to previous year if current year fails
if ((is.null(teams) || nrow(teams) == 0) && year >= 2025) {
  fallback_year <- 2024
  cat(sprintf("Falling back to %d data...\n", fallback_year))
  year <- fallback_year # Update global year for subsequent calls
  teams <- tryCatch({
    result <- baseballr::ncaa_teams(division = division, year = year)
    cat(sprintf("  -> Got %d rows for fallback year %d\n", if(!is.null(result)) nrow(result) else 0, year))
    result
  }, error = function(e) {
    cat(sprintf("ERROR calling ncaa_teams for fallback %d: %s\n", year, e$message))
    return(NULL)
  })
}

if (is.null(teams) || nrow(teams) == 0) {
  cat(sprintf("ERROR: No teams found for Division %d, Year %d (or fallback)!\n", division, year))
  cat("Check network connectivity or if the NCAA site has changed its structure.\n")
  quit(status = 1)
}


# Save teams list
teams_file <- file.path(output_dir, sprintf("teams_d%d.json", division))
write(toJSON(teams, auto_unbox = TRUE, pretty = TRUE), teams_file)
cat(sprintf("Saved %d teams to %s\n", nrow(teams), teams_file))

# Generate mapping table for Python (Name/ID -> Numeric ID)
# This includes safe_id versions for fast lookup
mapping <- teams %>%
  mutate(
    safe_id = gsub("[^[:alnum:]]", "_", team_name),
    safe_id = gsub("__+", "_", safe_id),
    safe_id = gsub("^_|_$", "", safe_id)
  )

mapping_file <- file.path(output_dir, sprintf("team_mapping_d%d.json", division))
write(toJSON(mapping, auto_unbox = TRUE, pretty = TRUE), mapping_file)

# 2. Handle specific team request (numeric or name-based)
if (!is.na(team_id_arg)) {
  if (!is.na(team_id)) {
    # Numeric ID provided
    teams_to_import <- teams[teams$team_id == team_id, ]
  } else {
    # Name or Safe ID provided
    cat(sprintf("Resolving numeric ID for: %s\n", team_id_arg))
    
    # 1. Try exact match on team_name
    match <- teams[teams$team_name == team_id_arg, ]
    
    # 2. Try match on mapping$safe_id
    if (nrow(match) == 0) {
      # Use the mapping created earlier
      match <- mapping[mapping$safe_id == team_id_arg, ]
    }
    
    # 3. Try robust normalization match (alphanumeric only, lowercase)
    if (nrow(match) == 0) {
      cat("  -> No exact match, trying normalized lookup...\n")
      normalize <- function(x) tolower(gsub("[^[:alnum:]]", "", x))
      target_norm <- normalize(team_id_arg)
      
      teams$name_norm <- normalize(teams$team_name)
      match <- teams[teams$name_norm == target_norm, ]
      
      # Also try matching the safe_id normalized
      if (nrow(match) == 0) {
         mapping$id_norm <- normalize(mapping$safe_id)
         match_idx <- which(mapping$id_norm == target_norm)
         if (length(match_idx) > 0) match <- teams[match_idx, ]
      }
    }
    
    # 4. Try case-insensitive substr match if still nothing
    if (nrow(match) == 0) {
      match <- teams[grepl(team_id_arg, teams$team_name, ignore.case = TRUE), ]
    }
    
    if (nrow(match) > 0) {
      teams_to_import <- match[1, ] # Take first match
      cat(sprintf("  -> Resolved to %s (ID: %d)\n", teams_to_import$team_name, teams_to_import$team_id))
      team_id <- teams_to_import$team_id # Update for stats fetching
    } else {
      cat(sprintf("ERROR: Could not resolve team: %s\n", team_id_arg))
      quit(status = 1)
    }
  }
} else {
  # Full import requested
  teams_to_import <- teams
  cat(sprintf("Importing stats for ALL %d teams...\n", nrow(teams_to_import)))
}

# 3. Import stats for each team
cat(sprintf("\n=== Importing Team Stats (%d teams) ===\n", nrow(teams_to_import)))

for (i in 1:nrow(teams_to_import)) {
  team <- teams_to_import[i, ]
  team_name <- team$team_name
  tid <- team$team_id
  
  cat(sprintf("\n[%d/%d] %s (ID: %d)\n", i, nrow(teams_to_import), team_name, tid))
  
  # Determine filename ID
  file_id <- if(!is.na(custom_id)) custom_id else as.character(tid)
  
  # Batting stats
  batting <- safe_fetch(
    baseballr::ncaa_team_player_stats(team_id = tid, year = year, type = "batting"),
    "batting stats"
  )
  if (!is.null(batting) && nrow(batting) > 0) {
    write.csv(batting, file.path(output_dir, "stats", sprintf("%s_batting.csv", file_id)), row.names = FALSE)
  }
  
  # Pitching stats
  pitching <- safe_fetch(
    baseballr::ncaa_team_player_stats(team_id = tid, year = year, type = "pitching"),
    "pitching stats"
  )
  if (!is.null(pitching) && nrow(pitching) > 0) {
    write.csv(pitching, file.path(output_dir, "stats", sprintf("%s_pitching.csv", file_id)), row.names = FALSE)
  }
  
  # Schedule/results
  schedule <- safe_fetch(
    baseballr::ncaa_schedule_info(team_id = tid, year = year),
    "schedule"
  )
  if (!is.null(schedule) && nrow(schedule) > 0) {
    write.csv(schedule, file.path(output_dir, "schedules", sprintf("%s_schedule.csv", file_id)), row.names = FALSE)
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
