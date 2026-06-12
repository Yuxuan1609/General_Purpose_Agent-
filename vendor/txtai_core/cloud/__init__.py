"""Stub CloudFactory — cloud storage not needed for local-only KB."""
from __future__ import annotations


class CloudFactory:
    @staticmethod
    def create(config):
        return None

    @staticmethod
    def load(cloud, path):
        return None

    @staticmethod
    def exists(cloud, path):
        return False

    @staticmethod
    def delete(cloud, path):
        pass


class ObjectStorage:
    pass
