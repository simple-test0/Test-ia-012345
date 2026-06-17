"""Unit tests for the Labs dataset loader (no torch training, just conversion)."""
import importlib.util

import pytest

_HAS_TORCH = importlib.util.find_spec("torch") is not None
pytestmark = pytest.mark.skipif(not _HAS_TORCH, reason="torch not installed")


class _FakeSplit:
    """Minimal stand-in for a HF dataset split."""

    def __init__(self, data):
        self._data = data
        self.column_names = list(data.keys())

    def __getitem__(self, key):
        return self._data[key]


def test_image_columns_pixel_values():
    import numpy as np

    from services.labs.trainer import _tensor_dataset_from_hf

    split = _FakeSplit({
        "pixel_values": np.random.rand(8, 3, 16, 16).astype("float32"),
        "label": list(range(8)),
    })
    ds = _tensor_dataset_from_hf(split, {})
    assert len(ds) == 8
    x, y = ds[0]
    assert tuple(x.shape) == (3, 16, 16)


def test_nhwc_image_and_labels_alias():
    import numpy as np

    from services.labs.trainer import _tensor_dataset_from_hf

    split = _FakeSplit({
        "image": (np.random.rand(4, 8, 8, 3) * 255).astype("uint8"),
        "labels": [0, 1, 0, 1],
    })
    ds = _tensor_dataset_from_hf(split, {})
    x, _ = ds[0]
    assert tuple(x.shape) == (3, 8, 8)  # converted NHWC -> NCHW
    assert float(x.max()) <= 1.0  # normalized


def test_text_column():
    from services.labs.trainer import _tensor_dataset_from_hf

    split = _FakeSplit({
        "text": ["hello world", "foo bar baz"],
        "target": [1, 0],
    })
    ds = _tensor_dataset_from_hf(split, {"max_seq_len": 16, "vocab_size": 500})
    x, _ = ds[0]
    assert tuple(x.shape) == (16,)


def test_missing_columns_raises():
    from services.labs.trainer import _tensor_dataset_from_hf

    split = _FakeSplit({"foo": [1, 2], "bar": [3, 4]})
    with pytest.raises(ValueError):
        _tensor_dataset_from_hf(split, {})
