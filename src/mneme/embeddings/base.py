from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch-Embedding. Returns list of vectors."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension of this model."""
        ...
