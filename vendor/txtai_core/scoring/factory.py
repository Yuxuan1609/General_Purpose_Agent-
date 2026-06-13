"""
Factory module
"""

from ..util import Resolver

from .bm25 import BM25
from .tfidf import TFIDF


class ScoringFactory:
    """
    Methods to create Scoring indexes.
    """

    @staticmethod
    def create(config, models=None):
        """
        Factory method to construct a Scoring instance.

        Args:
            config: scoring configuration parameters
            models: models cache

        Returns:
            Scoring
        """

        # Scoring instance
        scoring = None

        # Support string and dict configuration
        if isinstance(config, str):
            config = {"method": config}

        # Get scoring method
        method = config.get("method", "bm25")

        if method == "bm25":
            scoring = BM25(config)
        elif method == "tfidf":
            scoring = TFIDF(config)
        else:
            # Resolve custom method
            scoring = ScoringFactory.resolve(method, config)

        # Store config back
        config["method"] = method

        return scoring

    @staticmethod
    def issparse(config):
        """
        Checks if this scoring configuration builds a sparse index.

        Args:
            config: scoring configuration

        Returns:
            True if this config is for a sparse index
        """

        # No sparse index backends in stripped version
        return False

    @staticmethod
    def resolve(backend, config):
        """
        Attempt to resolve a custom backend.

        Args:
            backend: backend class
            config: index configuration parameters

        Returns:
            Scoring
        """

        try:
            return Resolver()(backend)(config)
        except Exception as e:
            raise ImportError(f"Unable to resolve scoring backend: '{backend}'") from e
