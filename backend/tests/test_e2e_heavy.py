"""End-to-end tests that exercise the real ML stack.

Marked `heavy` and skipped automatically when torch/diffusers aren't installed
(e.g. the light CI). Run locally with: pytest -m heavy
"""
import importlib.util

import pytest

pytestmark = pytest.mark.heavy

_HAS_TORCH = importlib.util.find_spec("torch") is not None
_HAS_DIFFUSERS = importlib.util.find_spec("diffusers") is not None


@pytest.mark.skipif(not (_HAS_TORCH and _HAS_DIFFUSERS), reason="torch/diffusers not installed")
def test_apply_sampler_swaps_scheduler():
    """The sampler mapping should resolve to real diffusers scheduler classes."""
    import diffusers

    from services.image_gen.pipeline_manager import _SAMPLER_MAP

    for _name, (cls_name, _kwargs) in _SAMPLER_MAP.items():
        assert getattr(diffusers, cls_name, None) is not None
