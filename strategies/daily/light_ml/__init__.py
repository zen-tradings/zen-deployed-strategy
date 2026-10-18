"""Light-ML filters (optional, daily only).

These are *filters applied on top of rule signals*, never primary signals.
Models are trained and frozen in the research repo; this package only loads
the exported artifact and applies it at inference time.
"""
