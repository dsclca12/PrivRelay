"""Opt-in synthetic-data generation. Never accepts raw SMS message inputs."""

from .synthetic import CATEGORIES, generate_synthetic

__all__ = ["CATEGORIES", "generate_synthetic"]
