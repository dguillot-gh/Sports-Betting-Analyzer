"""Unit tests for api.json_utils.sanitize_for_json."""
import json

import numpy as np

from api.json_utils import sanitize_for_json


def test_none_and_scalars_passthrough():
    assert sanitize_for_json(None) is None
    assert sanitize_for_json(42) == 42
    assert sanitize_for_json("x") == "x"
    assert sanitize_for_json(3.14) == 3.14
    assert sanitize_for_json(True) is True


def test_numpy_scalars_converted():
    assert sanitize_for_json(np.bool_(True)) is True
    assert sanitize_for_json(np.int64(5)) == 5
    assert isinstance(sanitize_for_json(np.int64(5)), int)
    assert sanitize_for_json(np.float64(1.5)) == 1.5
    assert isinstance(sanitize_for_json(np.float64(1.5)), float)


def test_nan_and_inf_become_none():
    assert sanitize_for_json(np.float64("nan")) is None
    assert sanitize_for_json(np.float64("inf")) is None
    assert sanitize_for_json(np.float64("-inf")) is None


def test_ndarray_to_list():
    arr = np.array([1, 2, 3])
    out = sanitize_for_json(arr)
    assert out == [1, 2, 3]


def test_nested_structures_recursed():
    obj = {
        "a": np.int64(1),
        "b": [np.float64("nan"), np.bool_(False)],
        "c": {"d": np.array([0.5, 1.5])},
    }
    out = sanitize_for_json(obj)
    assert out == {"a": 1, "b": [None, False], "c": {"d": [0.5, 1.5]}}


def test_tuple_type_preserved():
    out = sanitize_for_json((np.int64(1), np.int64(2)))
    assert isinstance(out, tuple)
    assert out == (1, 2)


def test_result_is_json_serializable():
    obj = {"n": np.int32(7), "f": np.float32(2.5), "arr": np.array([[1.0]]), "b": np.bool_(True)}
    s = json.dumps(sanitize_for_json(obj))
    assert json.loads(s)["n"] == 7
