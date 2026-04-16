from mneme.embeddings.base import EmbeddingProvider


def get_provider(config) -> EmbeddingProvider:
    """Create embedding provider from config.

    config needs .provider (str) and .model (str) attributes.
    For the ONNX provider, config also needs .backend (str).
    """
    if config.provider == "sentence-transformers":
        from mneme.embeddings.sentence_transformers import SentenceTransformersProvider
        return SentenceTransformersProvider(
            model_name=config.model,
            device=getattr(config, "device", "auto"),
            dtype=getattr(config, "dtype", "bfloat16"),
            batch_size=getattr(config, "batch_size", 32),
        )
    if config.provider == "onnx":
        from mneme.embeddings.onnx_provider import ONNXProvider
        return ONNXProvider(
            config.model,
            backend=getattr(config, "backend", "cpu"),
        )
    raise ValueError(f"Unknown embedding provider: {config.provider}")
