try:
    import sportsdataverse as sdv
    print(f"SDV Version: {sdv.__version__}")
except Exception as e:
    print(f"Could not get SDV version: {e}")

try:
    import sportsdataverse.cfb as cfb
    print("\n--- sportsdataverse.cfb attributes ---")
    for attr in dir(cfb):
        if not attr.startswith("_"):
            print(attr)
except ImportError as e:
    print(f"\nImportError: {e}")
except Exception as e:
    print(f"\nError: {e}")
