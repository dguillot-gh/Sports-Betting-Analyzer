
try:
    import ncaa_bbStats
    print("Imported ncaa_bbStats successfully")
    print(dir(ncaa_bbStats))
except ImportError:
    print("Failed to import ncaa_bbStats")
    
try:
    from ncaa_bbStats import ncaa_bbStats as stats
    print("Imported ncaa_bbStats submodule")
    print(dir(stats))
except ImportError:
    pass
