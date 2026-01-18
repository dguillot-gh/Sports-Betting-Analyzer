import pandas as pd
import numpy as np
import json
import joblib
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

# Config
DATA_DIR = Path(__file__).parent.parent / "data" / "nascar"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "nascar" / "archetypes"
CSV_PATH = DATA_DIR / "cup_enhanced.csv"

def train_archetypes():
    print("="*60)
    print("NASCAR Driver Archetype Clustering")
    print("="*60)
    
    # Ensure output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Load Data
    if not CSV_PATH.exists():
        print(f"Error: {CSV_PATH} not found. Run enhance_nascar_data.py first.")
        return
        
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} rows.")
    
    # 2. Prepare Driver Stats (Aggregated)
    # We want a single snapshot per driver to cluster them.
    # Approach: Take the weighted average of their recent stats or their career stats as of the latest race.
    # Better: Use the latest available career stats for each driver.
    
    # Sort by date
    df = df.sort_values(['year', 'race_num'])
    
    # Get the last row for each driver (most current stats)
    # Filter for drivers with enough races (e.g. > 10) to avoid noise
    driver_stats = df.groupby('driver').last().reset_index()
    driver_stats = driver_stats[driver_stats['career_races'] >= 10].copy()
    
    print(f"Clustering {len(driver_stats)} drivers with >10 races.")
    
    # Features for Clustering
    # - Career Avg Finish (Performance)
    # - Career Win % (Peak Dominance)
    # - Consistency Score (Reliability)
    # - Career Laps Led % (True speed/dominance)
    # - Career Top 5 (Podium contention)
    
    features = ['career_avg_finish', 'career_win_pct', 'consistency_score', 'career_laps_led_pct']
    
    X = driver_stats[features].fillna(0)
    
    # 3. Normalize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # 4. Train K-Means
    # Research suggests ~6 archetypes: 
    # Elite, Winner, Contender, Journeyman, Mid-Pack, Backfield
    k = 6
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_scaled)
    
    driver_stats['cluster'] = labels
    
    # 5. Analyze Clusters & Assign Names
    # We need to dynamically name the clusters based on their centroids to ensure "Elite" is actually the best one.
    
    cluster_summary = driver_stats.groupby('cluster')[features].mean()
    print("\nCluster Centroids:")
    print(cluster_summary)
    
    # Logic to name clusters
    # Elite: Best Finish (Lowest), High Win%, High Laps Led
    # Backmarker: Worst Finish (Highest), Low Win%
    
    # Rank clusters by Avg Finish (Ascending is better)
    ranked_clusters = cluster_summary.sort_values('career_avg_finish')
    
    # Simple mapping based on rank (0 = Best, 5 = Worst)
    rank_map = {
        0: "Elite Champion",      # ~Top tier
        1: "Race Winner",         # High potential
        2: "Consistent Pro",      # Good finish, low variance
        3: "Veteran Journeyman",  # Mid-tier
        4: "Mid-Pack",           # Lower mid
        5: "Development/Field"    # Back markers
    }
    
    # IMPORTANT: The 'rank' is the index in the SORTED dataframe. 
    # The 'cluster_id' is the index name.
    
    archetype_map = {}
    for rank, (cluster_id, row) in enumerate(ranked_clusters.iterrows()):
        name = rank_map.get(rank, "Unknown")
        archetype_map[int(cluster_id)] = name
        print(f"Cluster {cluster_id} -> {name} (AvgFin: {row['career_avg_finish']:.1f}, Win%: {row['career_win_pct']:.1%})")
        
    # Apply names
    driver_stats['archetype'] = driver_stats['cluster'].map(archetype_map)
    
    # 6. Save Artifacts
    
    # A. Save Models
    joblib.dump(scaler, OUTPUT_DIR / "scaler.joblib")
    joblib.dump(kmeans, OUTPUT_DIR / "kmeans.joblib")
    
    # B. Save Mapping JSON (Driver -> Archetype)
    mapping = driver_stats.set_index('driver')['archetype'].to_dict()
    
    # Also save the features per cluster for reference
    profiles = {}
    for cid, name in archetype_map.items():
        row = cluster_summary.loc[cid]
        profiles[name] = {
            "avg_finish": round(row['career_avg_finish'], 1),
            "win_pct": round(row['career_win_pct'], 3),
            "consistency": round(row['consistency_score'], 2),
            "laps_led_pct": round(row['career_laps_led_pct'], 3)
        }
    
    output_data = {
        "mapping": mapping,
        "profiles": profiles,
        "updated_at": str(pd.Timestamp.now())
    }
    
    with open(OUTPUT_DIR / "driver_archetypes.json", "w") as f:
        json.dump(output_data, f, indent=2)
        
    print(f"\nSaved models and mapping to {OUTPUT_DIR}")
    
    # Preview
    print("\nSample Assignments:")
    print(driver_stats[['driver', 'archetype', 'career_avg_finish']].head(10))

if __name__ == "__main__":
    train_archetypes()
