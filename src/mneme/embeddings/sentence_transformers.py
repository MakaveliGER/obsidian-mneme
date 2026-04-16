import logging
import time

from mneme.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class SentenceTransformersProvider(EmbeddingProvider):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            logger.info("Loading embedding model: %s", self.model_name)
            t0 = time.monotonic()

            from sentence_transformers import SentenceTransformer
            t1 = time.monotonic()
            logger.info("  import sentence_transformers: %.1fs", t1 - t0)

            import torch

            model_kwargs = {}
            # bfloat16 + SDPA: ~22% faster embedding, ~8% less RAM
            if hasattr(torch, "bfloat16"):
                model_kwargs["dtype"] = torch.bfloat16
                model_kwargs["attn_implementation"] = "sdpa"

            self._model = SentenceTransformer(self.model_name, model_kwargs=model_kwargs)
            t2 = time.monotonic()
            logger.info("  model loaded: %.1fs", t2 - t1)
            logger.info("  total load time: %.1fs", t2 - t0)
        return self._model

    def warmup(self) -> None:
        """Pre-load the model. Call at startup to avoid first-query latency."""
        self._load_model()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._load_model().encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

    def dimension(self) -> int:
        model = self._load_model()
        if hasattr(model, "get_embedding_dimension"):
            return model.get_embedding_dimension()
        return model.get_sentence_embedding_dimension()
