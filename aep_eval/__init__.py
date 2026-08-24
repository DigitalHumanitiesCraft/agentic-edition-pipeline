"""Evaluation module of the Agentic Edition Pipeline, v0.1.

Reads a fixture manifest, computes character error rates under declared
normalisation profiles and checks TEI files against an explicitly named
RelaxNG schema; writes one result set as JSON and Markdown. Inputs are read
only, nothing in a fixture repository is touched.

Contract: decision ADR-006 in knowledge/decisions.md, which records the
implementation contract, the two profiles and their regression anchors.
Usage: `python -m aep_eval MANIFEST --out DIR`.
"""

from __future__ import annotations

__version__ = "0.1.0"
