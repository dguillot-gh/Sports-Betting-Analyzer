
try:
    import ncaa_stats
    print("Imported ncaa_stats")
    print(dir(ncaa_stats))
except ImportError:
    pass

try:
    import ncaa_bbstats
    print("Imported ncaa_bbstats (lowercase)")
    print(dir(ncaa_bbstats))
except ImportError as e:
    print(f"Failed to import ncaa_bbstats: {e}")

try:
    import ncaa_bbStats
    print("Imported ncaa_bbStats (camel)")
except ImportError:
    pass
