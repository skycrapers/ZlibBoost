"""Utility hooks for preprocessing simulator-specific SPICE decks."""

from .ngspice import preprocess_deck_tree as preprocess_ngspice_decks

__all__ = ["preprocess_ngspice_decks"]
