from mneme.embeddings.base import EmbeddingProvider


def get_provider(config) -> EmbeddingProvider:
    """Create embedding provider from config.

    config needs .provider (str) and .model (str) attributes.
    For the ONNX provider, config also needs .backend (str).
    """
    if config.provider == "sentence-transformers":
        from mneme.embeddings.sentence_transformers import SentenceTransformersProvider
        return SentenceTransformersProvider(config.model)
    if config.provider == "onnx":
        from mneme.embeddings.onnx_provider import ONNXProvider
        return ONNXProvider(
            config.model,
            backend=getattr(config, "backend", "cpu"),
        )
    raise ValueError(f"Unknown embedding provider: {config.provider}")
