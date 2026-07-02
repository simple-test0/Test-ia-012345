"""Guard: the backend must import and build its app WITHOUT torch/diffusers.

Heavy ML deps (torch, diffusers, PIL) are imported lazily throughout the code so
the app can boot on a machine without a GPU (and in light CI). If a module-level
heavy import sneaks back in, importing `main` here will fail and catch it.
"""


def test_app_imports_without_torch():
    import main

    assert main.app is not None
    paths = {getattr(r, "path", None) for r in main.app.routes}
    assert "/health" in paths
    # Routers (REST + WS) are wired up on top of the default docs routes.
    assert len(main.app.routes) > 5


def test_architecture_registry_imports_without_torch():
    # Metadata access must not pull in torch.
    from services.labs.architecture_registry import get_arch, list_archs

    archs = list_archs()
    assert {a.id for a in archs} >= {"cnn", "rnn", "lstm", "gru", "transformer", "vit"}
    assert get_arch("cnn").default_config["num_classes"] == 10
