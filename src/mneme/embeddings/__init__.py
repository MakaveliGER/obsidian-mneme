from mneme.embeddings.base import EmbeddingProvider


def get_provider(config) -> EmbeddingProvider:
    """Create embedding provider from config.

    config needs .provider (str) and .model (str) attributes.
    """
    if config.provider == "sentence-transformers":
        from mneme.embeddings.sentence_transformers import SentenceTransformersProvider
        return SentenceTransformersProvider(config.model)
    raise ValueError(f"Unknown embedding provider: {config.provider}")
