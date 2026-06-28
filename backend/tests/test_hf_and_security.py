
from types import SimpleNamespace

from core import security
from core.config import settings
from services.image_gen import hf_connector


def test_repo_cache_path_format():
    p = hf_connector._repo_cache_path("org/Model-Name")
    assert p.name == "models--org--Model-Name"


def test_param_count_from_total():
    m = SimpleNamespace(safetensors=SimpleNamespace(total=2_600_000_000, parameters={}))
    assert hf_connector._param_count(m) == 2_600_000_000


def test_param_count_sums_parameters_when_no_total():
    m = SimpleNamespace(safetensors=SimpleNamespace(total=None, parameters={"F16": 100, "F32": 50}))
    assert hf_connector._param_count(m) == 150


def test_param_count_missing_safetensors():
    assert hf_connector._param_count(SimpleNamespace(safetensors=None)) == 0


def _sibling(name, size):
    return SimpleNamespace(rfilename=name, size=size)


def test_estimate_download_bytes_prefers_fp16():
    siblings = [
        _sibling("unet/diffusion_pytorch_model.safetensors", 10),       # fp32 safetensors
        _sibling("unet/diffusion_pytorch_model.fp16.safetensors", 5),   # fp16 variant
        _sibling("unet/diffusion_pytorch_model.bin", 10),               # pytorch bin
        _sibling("model_index.json", 1),                                # config
    ]
    # fp16 weights (5) + non-weight files (1); fp32 + .bin are skipped.
    assert hf_connector._estimate_download_bytes(siblings) == 6


def test_estimate_download_bytes_falls_back_to_safetensors():
    siblings = [
        _sibling("unet/diffusion_pytorch_model.safetensors", 8),
        _sibling("unet/diffusion_pytorch_model.bin", 8),
        _sibling("config.json", 2),
    ]
    assert hf_connector._estimate_download_bytes(siblings) == 10


def test_search_hf_models_enriches_params_and_size(monkeypatch):
    fake_model = SimpleNamespace(
        id="org/cool-model",
        downloads=123,
        likes=7,
        gated=False,
        pipeline_tag="text-to-image",
        tags=["sdxl"],
        safetensors=SimpleNamespace(total=1_000_000_000, parameters={}),
    )

    class FakeApi:
        def __init__(self, *a, **k):
            pass

        def list_models(self, *a, **k):
            return [fake_model]

    # search_hf_models does `from huggingface_hub import HfApi` at call time.
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)

    results = hf_connector.search_hf_models("cool")
    assert len(results) == 1
    r = results[0]
    assert r["params"] == 1_000_000_000
    assert r["size_bytes"] == 1_000_000_000 * hf_connector._BYTES_PER_PARAM_FP16


def test_download_progress_zero_total():
    assert hf_connector.download_progress("org/x", 0) == 0


def test_download_progress_no_dir(tmp_path, monkeypatch):
    # Point cache at an empty temp dir -> 0% progress.
    monkeypatch.setattr(settings, "models_dir", tmp_path)
    assert hf_connector.download_progress("org/missing", 1000) == 0


def test_ws_token_disabled(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "")
    assert security.ws_token_ok("anything") is True
    assert security.ws_token_ok("") is True


def test_ws_token_enabled(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret")
    assert security.ws_token_ok("secret") is True
    assert security.ws_token_ok("wrong") is False
