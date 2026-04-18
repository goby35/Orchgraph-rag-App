import modal

app = modal.App("orchgraph-rag")

# Image with project dependencies
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
)

# Shared volume for model cache to avoid repeated downloads on cold start
model_volume = modal.Volume.from_name("orchgraph-models", create_if_missing=True)


@app.function(volumes={"/models": model_volume})
def download_models() -> None:
    from sentence_transformers import SentenceTransformer

    SentenceTransformer("Alibaba-NLP/gte-multilingual-base", cache_folder="/models")
    model_volume.commit()


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("orchgraph-secrets")],
    volumes={"/models": model_volume},
    timeout=300,
)
@modal.concurrent(max_inputs=10)
@modal.asgi_app()
def fastapi_app():
    from api.main import app as fastapi_backend_app
    
    # Preload embedding models at container startup to avoid cold-start latency
    @fastapi_backend_app.on_event("startup")
    async def warmup_models():
        import os
        from sentence_transformers import SentenceTransformer
        from pipeline.config import get_logger
        
        logger = get_logger(__name__)
        logger.info("Modal startup: Preloading embedding models...")
        
        try:
            cache_dir = "/models" if os.path.isdir("/models") else None
            SentenceTransformer("Alibaba-NLP/gte-multilingual-base", cache_folder=cache_dir)
            logger.info("✓ GTE-multilingual model loaded successfully")
        except Exception as e:
            logger.warning(f"Model preload warning (non-fatal): {e}")

    return fastapi_backend_app
