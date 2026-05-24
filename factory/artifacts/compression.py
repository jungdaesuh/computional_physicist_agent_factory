# compression.py — Stream compression utilities for artifacts-at-rest
#
# This module implements gzip and zstd stream compression utilities for artifacts-at-rest.
# To minimize storage space and disk I/O, particularly when storing massive runs of
# Council deliberations, simulation logs, or validation results, artifacts are compressed.
#
# Supported formats:
# - gzip (standard library)
# - zstd (using zstandard package)
# - raw (no compression)
#
# Use cases:
# 1. Compressing and decompressing raw in-memory bytes using Literal or Enum methods.
# 2. Writing compressed artifacts directly to Path with auto-created parent directories.
# 3. Reading artifacts with signature-based detection or extension fallbacks.
# 4. Backward-compatible StrEnum and path compression helper interfaces.

from __future__ import annotations

import gzip
import logging
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Literal

# Try to import zstandard for zstd support.
try:
    import zstandard

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
    zstandard = None

logger = logging.getLogger("factory.artifacts.compression")

# Magic byte signatures
GZIP_MAGIC = b"\x1f\x8b"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class CompressionAlgorithm(StrEnum):
    """Compression algorithms supported by the artifact layer."""

    GZIP = "gzip"


SUPPORTED_COMPRESSION_ALGORITHMS: tuple[CompressionAlgorithm, ...] = (CompressionAlgorithm.GZIP,)


def compress_bytes(
    data: bytes,
    method: Literal["gzip", "zstd", "raw"] | CompressionAlgorithm = "gzip",
) -> bytes:
    """Compresses the input bytes using the specified compression method.

    Args:
        data: The raw uncompressed bytes.
        method: The compression method ('gzip', 'zstd', 'raw' or CompressionAlgorithm).

    Returns:
        The compressed bytes.
    """
    logger.info("compress_bytes(data_len=%d, method=%r)", len(data), method)
    # Map CompressionAlgorithm enum to string
    method_str = method.value if isinstance(method, CompressionAlgorithm) else method

    if method_str == "raw":
        return data
    elif method_str == "gzip":
        return gzip.compress(data, mtime=0)
    elif method_str == "zstd":
        if HAS_ZSTD and zstandard is not None:
            cctx = zstandard.ZstdCompressor()
            compressed_data: bytes = cctx.compress(data)
            return compressed_data
        raise ImportError("Cannot compress with zstd: 'zstandard' module is not installed.")
    else:
        raise ValueError(f"Unsupported compression method: {method}")


def decompress_bytes(
    data: bytes,
    method: Literal["gzip", "zstd", "raw"] | CompressionAlgorithm = "gzip",
) -> bytes:
    """Decompresses the input bytes using the specified compression method.

    Args:
        data: The compressed bytes.
        method: The compression method ('gzip', 'zstd', 'raw' or CompressionAlgorithm).

    Returns:
        The decompressed raw bytes.
    """
    logger.info("decompress_bytes(data_len=%d, method=%r)", len(data), method)
    # Map CompressionAlgorithm enum to string
    method_str = method.value if isinstance(method, CompressionAlgorithm) else method

    if method_str == "raw":
        return data
    elif method_str == "gzip":
        return gzip.decompress(data)
    elif method_str == "zstd":
        if HAS_ZSTD and zstandard is not None:
            dctx = zstandard.ZstdDecompressor()
            decompressed_data: bytes = dctx.decompress(data)
            return decompressed_data
        raise ImportError(
            "Cannot decompress zstd-compressed data: 'zstandard' module is not installed."
        )
    else:
        raise ValueError(f"Unsupported compression method: {method}")


def write_compressed_artifact(
    path: Path,
    data: bytes,
    method: Literal["gzip", "zstd", "raw"] | CompressionAlgorithm = "gzip",
) -> None:
    """Compresses data and writes it to the specified file path atomically.

    Creates parent directories if they do not exist.

    Args:
        path: Path to the destination file.
        data: Raw uncompressed bytes.
        method: Compression method ('gzip', 'zstd', 'raw' or CompressionAlgorithm).
    """
    logger.info(
        "write_compressed_artifact(path=%s, data_len=%d, method=%r)",
        path,
        len(data),
        method,
    )
    compressed = compress_bytes(data, method=method)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=path.parent,
        prefix=f".{path.name}.",
    ) as temp_dir:
        temp_path = Path(temp_dir) / path.name
        with temp_path.open("xb") as temp_file:
            temp_file.write(compressed)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)


def read_compressed_artifact(path: Path) -> bytes:
    """Reads a compressed file from the path, auto-detecting the compression method.

    The method is detected based on the file signature (magic bytes) first,
    and falls back to checking the file extension if no signature matches.

    Args:
        path: Path to the compressed artifact file.

    Returns:
        The decompressed raw bytes.
    """
    logger.info("read_compressed_artifact(path=%s)", path)
    if not path.exists():
        raise FileNotFoundError(f"Compressed artifact file not found: {path}")

    # Read up to 4 bytes for signature check
    with open(path, "rb") as f:
        signature = f.read(4)

    if signature.startswith(GZIP_MAGIC):
        method: Literal["gzip", "zstd", "raw"] = "gzip"
    elif signature.startswith(ZSTD_MAGIC):
        method = "zstd"
    else:
        # Fall back to extension-based detection
        suffix = path.suffix.lower()
        if suffix == ".gz":
            method = "gzip"
        elif suffix in (".zst", ".zstd"):
            method = "zstd"
        else:
            method = "raw"

    with open(path, "rb") as f:
        compressed_data = f.read()

    return decompress_bytes(compressed_data, method=method)


# Legacy backwards-compatibility helpers
def write_compressed_bytes(
    destination_path: Path,
    content: bytes,
    algorithm: CompressionAlgorithm,
) -> Path:
    """Atomically write compressed bytes to destination_path using legacy helpers."""
    logger.info(
        "write_compressed_bytes(destination_path=%s, content_len=%d, algorithm=%r)",
        destination_path,
        len(content),
        algorithm,
    )
    write_compressed_artifact(destination_path, content, method=algorithm)
    return destination_path


def read_compressed_bytes(source_path: Path, algorithm: CompressionAlgorithm) -> bytes:
    """Read and decompress a compressed file into bytes using legacy helpers."""
    logger.info(
        "read_compressed_bytes(source_path=%s, algorithm=%r)",
        source_path,
        algorithm,
    )
    return decompress_bytes(source_path.read_bytes(), method=algorithm)


def compress_path(
    source_path: Path,
    destination_path: Path,
    algorithm: CompressionAlgorithm,
) -> Path:
    """Atomically compress one file to another path using legacy helpers."""
    logger.info(
        "compress_path(source_path=%s, destination_path=%s, algorithm=%r)",
        source_path,
        destination_path,
        algorithm,
    )
    data = source_path.read_bytes()
    write_compressed_artifact(destination_path, data, method=algorithm)
    return destination_path


def decompress_path(
    source_path: Path,
    destination_path: Path,
    algorithm: CompressionAlgorithm,
) -> Path:
    """Atomically decompress one file to another path using legacy helpers."""
    logger.info(
        "decompress_path(source_path=%s, destination_path=%s, algorithm=%r)",
        source_path,
        destination_path,
        algorithm,
    )
    data = read_compressed_bytes(source_path, algorithm)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=destination_path.parent,
        prefix=f".{destination_path.name}.",
    ) as temp_dir:
        temp_path = Path(temp_dir) / destination_path.name
        with temp_path.open("xb") as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, destination_path)
    return destination_path
