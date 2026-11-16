"""Bound the caches without throwing everything away.

Previously the caches were cleared completely on overflow - with more surfaces than slots, EVERY frame rebuilt every
surface (harbor test 09.11.: from 256 surfaces ~3 s per change). trim() discards only the older half (dicts keep
insertion order); what is being used right now is at the end and stays.
"""


def trim(cache, limit):
    """Call before inserting: if cache is full (> limit), remove the older half."""
    if len(cache) > limit:
        for k in list(cache)[:len(cache) // 2]:
            cache.pop(k, None)  # (not del: two threads may trim at the same time, e.g. the normals in the renderer)
