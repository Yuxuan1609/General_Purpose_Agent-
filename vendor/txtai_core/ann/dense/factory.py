"""
Factory module
"""

from ...util import Resolver

from .numpy import NumPy


class ANNFactory:
    """
    Methods to create ANN indexes.
    """

    @staticmethod
    def create(config):
        """
        Create an ANN.

        Args:
            config: index configuration parameters

        Returns:
            ANN
        """

        # ANN instance
        ann = None
        backend = config.get("backend", "numpy")

        # Create ANN instance
        if backend == "numpy":
            ann = NumPy(config)
        else:
            ann = ANNFactory.resolve(backend, config)

        # Store config back
        config["backend"] = backend

        return ann

    @staticmethod
    def resolve(backend, config):
        """
        Attempt to resolve a custom backend.

        Args:
            backend: backend class
            config: index configuration parameters

        Returns:
            ANN
        """

        try:
            return Resolver()(backend)(config)
        except Exception as e:
            raise ImportError(f"Unable to resolve ann backend: '{backend}'") from e
