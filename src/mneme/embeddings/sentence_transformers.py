from mneme.embeddings.base import EmbeddingProvider


class SentenceTransformersProvider(EmbeddingProvider):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._load_model().encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

    def dimension(self) -> int:
        model = self._load_model()
        # get_sentence_embedding_dimension was renamed in newer versions
        if hasattr(model, "get_embedding_dimension"):
            return model.get_embedding_dimension()
        return model.get_sentence_embedding_dimension()
