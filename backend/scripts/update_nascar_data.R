# Update NASCAR Data using nascarR
# This script fetches the latest data for all series and saves to .rda files

# Install/Load required packages
if (!require("nascarR")) devtools::install_github("kylebennison/nascarR")
if (!require("dplyr")) install.packages("dplyr")

library(nascarR)
library(dplyr)

# Set Output Directory (Relative to script execution)
# Assuming script is run from backend/scripts/ or similar, target is ../data/nascar/raw
output_dir <- "../data/nascar/raw"
if (!dir.exists(output_dir)) dir.create(output_dir, recursive = TRUE)

# Series to fetch
years <- 2012:as.numeric(format(Sys.Date(), "%Y"))

print(paste("Fetching data for years:", min(years), "-", max(years)))

# 1. Cup Series
print("Fetching Cup Series data...")
cup_series <- nascar_race_results(years, series_id = 1)
saveRDS(cup_series, file = file.path(output_dir, "cup_series.rds")) # Save as RDS for easier R handling? Original used .rda via save()
# To match pyreadr extraction of .rda, we use save(). 
# Variable name in .rda is crucial.
save(cup_series, file = file.path(output_dir, "cup_series.rda"))

# 2. Xfinity Series
print("Fetching Xfinity Series data...")
xfinity_series <- nascar_race_results(years, series_id = 2)
save(xfinity_series, file = file.path(output_dir, "xfinity_series.rda"))

# 3. Truck Series
print("Fetching Truck Series data...")
truck_series <- nascar_race_results(years, series_id = 3)
save(truck_series, file = file.path(output_dir, "truck_series.rda"))

print("Data update complete!")
