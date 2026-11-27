"""Restricted loading for legacy NumPy-backed local profile files.

Pickle can execute arbitrary globals. This loader accepts only the small set of
NumPy reconstruction primitives needed by Jarvis's own array profiles.
"""
import codecs
import json
import os
import pickle
import tempfile

import numpy as np


class _RestrictedNumpyUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module in ("numpy.core.multiarray", "numpy._core.multiarray") and name == "_reconstruct":
            return np._core.multiarray._reconstruct
        if module == "numpy" and name == "ndarray":
            return np.ndarray
        if module == "numpy" and name == "dtype":
            return np.dtype
        if module == "_codecs" and name == "encode":
            return codecs.encode
        raise pickle.UnpicklingError(f"forbidden pickle global: {module}.{name}")


def load_numpy_pickle(path, max_bytes=10_000_000):
    """Load a bounded legacy pickle containing only primitive values and NumPy arrays."""
    size = os.path.getsize(path)
    if size > max_bytes:
        raise pickle.UnpicklingError(f"profile is too large ({size} bytes)")
    with open(path, "rb") as stream:
        return _RestrictedNumpyUnpickler(stream).load()



def atomic_json_write(path, data):
    """Write a JSON profile beside its destination and atomically replace it."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".jarvis-profile-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
