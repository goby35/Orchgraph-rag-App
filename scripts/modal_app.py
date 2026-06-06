import modal

app = modal.App("orchgraph-rag")

# Image with project dependencies
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
    .add_local_python_source("api", "pipeline")
)

# Shared volume for model cache to avoid repeated downloads on cold start
model_volume = modal.Volume.from_name("orchgraph-models", create_if_missing=True)


@app.function(volumes={"/models": model_volume})
def download_models() -> None:
    import os
    import shutil
    from pathlib import Path
    from sentence_transformers import SentenceTransformer

    modules_cache = "/tmp/hf_modules_stable"
    os.makedirs(modules_cache, exist_ok=True)
    os.environ["HF_MODULES_CACHE"] = modules_cache

    legacy_modules = Path(modules_cache) / "transformers_modules"
    if legacy_modules.exists():
        for candidate in legacy_modules.glob("Alibaba*"):
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)

    SentenceTransformer(
        "Alibaba-NLP/gte-multilingual-base",
        cache_folder="/models",
        trust_remote_code=True,
    )
    model_volume.commit()


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("orchgraph-secrets")],
    volumes={"/models": model_volume},
    timeout=300,
    gpu="L4"
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app()
def fastapi_app():
    from api.main import app as fastapi_backend_app
    
    # Preload embedding models at container startup to avoid cold-start latency
    @fastapi_backend_app.on_event("startup")
    async def warmup_models():
        import os
        import shutil
        from pathlib import Path
        from sentence_transformers import SentenceTransformer
        from pipeline.config import get_logger
        
        logger = get_logger(__name__)
        logger.info("Modal startup: Preloading embedding models...")
        
        try:
            cache_dir = "/models" if os.path.isdir("/models") else None
            modules_cache = "/tmp/hf_modules_stable"
            os.makedirs(modules_cache, exist_ok=True)
            os.environ["HF_MODULES_CACHE"] = modules_cache

            legacy_modules = Path(modules_cache) / "transformers_modules"
            if legacy_modules.exists():
                for candidate in legacy_modules.glob("Alibaba*"):
                    if candidate.is_dir():
                        shutil.rmtree(candidate, ignore_errors=True)

            SentenceTransformer(
                "Alibaba-NLP/gte-multilingual-base",
                cache_folder=cache_dir,
                trust_remote_code=True,
            )
            logger.info("✓ GTE-multilingual model loaded successfully")
        except Exception as e:
            logger.warning(f"Model preload warning (non-fatal): {e}")

    return fastapi_backend_app
