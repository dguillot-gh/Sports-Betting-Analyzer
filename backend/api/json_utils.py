"""Utilities for safe JSON serialization of numpy / pandas types."""
import numpy as np


def sanitize_for_json(obj):
    """Recursively convert numpy types to native Python types for JSON serialization.

    FastAPI's ``jsonable_encoder`` cannot handle ``numpy.bool_``,
    ``numpy.int64``, ``numpy.float64``, etc.  Run response dicts through
    this function before returning them from endpoints.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(sanitize_for_json(item) for item in obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        val = float(obj)
        # NaN / Inf are not valid JSON
        if val != val or val == float("inf") or val == float("-inf"):
            return None
        return val
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj
