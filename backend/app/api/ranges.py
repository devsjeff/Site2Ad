"""HTTP Range header parsing, so browsers (Safari in particular) can seek inside the ad video."""

from __future__ import annotations

import re
from typing import Optional

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeNotSatisfiable(Exception):
    """The requested range lies outside the file (answer 416)."""


def parse_range(header: Optional[str], size: int) -> Optional[tuple[int, int]]:
    """Return (start, end) inclusive for a single `bytes=` range, None when there is no usable range header.

    Multi-range requests are ignored (the full file is sent). Raises RangeNotSatisfiable for ranges past the end.
    """
    if not header or size <= 0:
        return None
    match = RANGE_RE.match(header.strip())
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None
    if not first:  # suffix range: the last N bytes
        count = int(last)
        if count == 0:
            raise RangeNotSatisfiable()
        return max(0, size - count), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start:
        raise RangeNotSatisfiable()
    return start, min(end, size - 1)


def read_slice(path, start: int, end: int) -> bytes:
    """Read bytes start..end (inclusive) from a file."""
    with open(path, "rb") as handle:
        handle.seek(start)
        return handle.read(end - start + 1)
