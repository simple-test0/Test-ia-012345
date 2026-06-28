
from services.image_gen import model_registry as mr


def test_curated_ids_and_repos_unique():
    models = mr.curated_models()
    ids = [m.id for m in models]
    repos = [m.repo_id for m in models]
    assert len(ids) == len(set(ids))
    assert len(repos) == len(set(repos))


def test_sd15_uses_maintained_mirror():
    # The old runwayml repo was removed from HF.
    assert mr.MODEL_REGISTRY_MAP["sd15"].repo_id == "stable-diffusion-v1-5/stable-diffusion-v1-5"
    for m in mr.curated_models():
        assert "runwayml" not in m.repo_id


def test_gated_models_flagged():
    assert mr.MODEL_REGISTRY_MAP["flux-dev"].gated is True
    assert mr.MODEL_REGISTRY_MAP["sd35-large"].gated is True
    assert mr.MODEL_REGISTRY_MAP["flux-schnell"].gated is False


async def test_resolve_curated(db_session):
    resolved = await mr.resolve_model("sd15", db_session)
    assert resolved is not None
    assert resolved.source == "curated"
    assert resolved.repo_id == "stable-diffusion-v1-5/stable-diffusion-v1-5"


async def test_resolve_missing(db_session):
    assert await mr.resolve_model("does-not-exist", db_session) is None


async def test_resolve_downloaded_ready(db_session):
    from models.diffusion_model import DiffusionModel

    rec = DiffusionModel(id="abc", name="m", repo_id="org/m", status="ready", min_vram_mb=1000)
    db_session.add(rec)
    await db_session.commit()

    resolved = await mr.resolve_model("abc", db_session)
    assert resolved is not None
    assert resolved.source == "downloaded"
    assert resolved.repo_id == "org/m"


async def test_resolve_downloaded_not_ready(db_session):
    from models.diffusion_model import DiffusionModel

    db_session.add(DiffusionModel(id="dl", name="m", repo_id="org/m2", status="downloading"))
    await db_session.commit()
    # Not ready -> not resolvable for generation.
    assert await mr.resolve_model("dl", db_session) is None
