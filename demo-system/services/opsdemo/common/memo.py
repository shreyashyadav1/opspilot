"""A per-request memo that never evicts: the memory-leak failure mode.

Every business request stores a buffer keyed by its path and request number, so resident memory
grows with traffic. Once the memo holds its budget, the next allocation fails with MemoryError,
which is what a Python process close to its memory limit raises. The control plane asks for at
least 128 KB per request, so the allocator maps each buffer separately and returns it to the OS
when the memo is cleared.
"""

from __future__ import annotations

import itertools
import threading


class RequestMemo:
    def __init__(self) -> None:
        self._entries: dict[str, bytes] = {}
        self._size = 0
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    @property
    def size_bytes(self) -> int:
        return self._size

    def remember(self, path: str, nbytes: int, budget_bytes: int) -> None:
        with self._lock:
            if self._size + nbytes > budget_bytes:
                raise MemoryError()
            # Filled rather than zeroed: zero pages from calloc are not resident until written.
            self._entries[f"{path}#{next(self._ids)}"] = b"\x5a" * nbytes
            self._size += nbytes

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._size = 0
