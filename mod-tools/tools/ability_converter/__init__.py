"""Structured FFBE to FFR ability compiler.

The public API is Converter.convert(SourceRecord). Table compatibility and
runtime verification are deliberately separate properties of its result.
"""
from .compiler import Converter
from .sources import SourceRecord

__all__ = ["Converter", "SourceRecord"]
