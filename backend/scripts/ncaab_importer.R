#!/usr/bin/env Rscript

# ncaab_importer.R
# Fetches NCAAB data using hoopR and saves to parquet

if (!require("hoopR")) install.packages("hoopR", repos="https://cloud.r-project.org")
if (!require("dplyr")) install.packages("dplyr", repos="https://cloud.r-project.org")
if (!require("arrow")) install.packages("arrow", repos="https://cloud.r-project.org")

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3) {
  stop("Usage: Rscript ncaab_importer.R <start_year> <end_year> <data_dir>")
}

start_year <- as.integer(args[1])
end_year <- as.integer(args[2])
data_dir <- args[3]

dir.create(data_dir, showWarnings = FALSE, recursive = TRUE)

cat(paste0("Starting hoopR NCAAB import for years: ", start_year, " to ", end_year, "\n"))

all_schedules <- list()
all_boxscores <- list()

for (year in start_year:end_year) {
  cat(paste0("Loading season: ", year, "...\n"))
  
  # 1. Schedule
  tryCatch({
    sched <- hoopR::load_mbb_schedule(seasons = year)
    if (nrow(sched) > 0) {
      all_schedules[[as.character(year)]] <- sched
    }
  }, error = function(e) {
    cat(paste0("Error loading schedule for ", year, ": ", e$message, "\n"))
  })
  
  # 2. Boxscores
  tryCatch({
    box <- hoopR::load_mbb_team_box(seasons = year)
    if (nrow(box) > 0) {
      all_boxscores[[as.character(year)]] <- box
    }
  }, error = function(e) {
    cat(paste0("Error loading boxscores for ", year, ": ", e$message, "\n"))
  })
}

# Combine and Save
if (length(all_schedules) > 0) {
  df_schedule <- bind_rows(all_schedules)
  schedule_path <- file.path(data_dir, "ncaab_schedule_history.parquet")
  arrow::write_parquet(df_schedule, schedule_path)
  cat(paste0("Saved ", nrow(df_schedule), " games to ", schedule_path, "\n"))
}

if (length(all_boxscores) > 0) {
  df_box <- bind_rows(all_boxscores)
  
  # Data Cleaning for Python Predictor
  # 1. Split combined strings like "10-25" into separate columns if they exist
  if ("field_goals_made_field_goals_attempted" %in% names(df_box)) {
    df_box <- df_box %>%
      mutate(
        field_goals_made = as.numeric(sub("-.*", "", field_goals_made_field_goals_attempted)),
        field_goals_attempted = as.numeric(sub(".*-", "", field_goals_made_field_goals_attempted))
      )
  }
  
  if ("free_throws_made_free_throws_attempted" %in% names(df_box)) {
    df_box <- df_box %>%
      mutate(
        free_throws_made = as.numeric(sub("-.*", "", free_throws_made_free_throws_attempted)),
        free_throws_attempted = as.numeric(sub(".*-", "", free_throws_made_free_throws_attempted))
      )
  }
  
  # 2. Ensure team_score and opponent_team_score exist
  # If they are named differently in this version of hoopR, map them
  if (!"team_score" %in% names(df_box) && "score" %in% names(df_box)) {
     df_box$team_score <- df_box$score
  }
  
  # 4. Ensure other stats are numeric
  stat_cols <- c("turnovers", "offensive_rebounds", "total_rebounds", "team_score", "opponent_team_score")
  for (col in stat_cols) {
    if (col %in% names(df_box)) {
      df_box[[col]] <- as.numeric(df_box[[col]])
    }
  }

  box_path <- file.path(data_dir, "ncaab_team_box_history.parquet")
  arrow::write_parquet(df_box, box_path)
  cat(paste0("Saved ", nrow(df_box), " boxscores to ", box_path, "\n"))
}

cat("NCAAB Import Complete!\n")
