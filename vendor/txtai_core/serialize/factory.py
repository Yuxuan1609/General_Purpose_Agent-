"""
Factory module
"""

from .messagepack import MessagePack


class SerializeFactory:
    """
    Methods to create data serializers.
    """

    @staticmethod
    def create(method=None, **kwargs):
        """
        Creates a new Serialize instance.

        Args:
            method: serialization method
            kwargs: additional keyword arguments to pass to serialize instance
        """

        # Default serialization
        return MessagePack(**kwargs)
