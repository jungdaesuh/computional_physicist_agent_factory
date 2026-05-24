# test_compression.py — Unit tests for artifact compression utilities
#
# This file validates the correctness of the compression/decompression methods,
# signature-based and extension-based auto-detection, explicit zstd dependency
# failures, and file I/O operations.

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from factory.artifacts.compression import (
    GZIP_MAGIC,
    SUPPORTED_COMPRESSION_ALGORITHMS,
    ZSTD_MAGIC,
    CompressionAlgorithm,
    compress_bytes,
    decompress_bytes,
    read_compressed_artifact,
    read_compressed_bytes,
    write_compressed_artifact,
    write_compressed_bytes,
)

logger = logging.getLogger("factory.artifacts.tests.compression")


# Legacy test cases (from other subagent)
def test_gzip_bytes_roundtrip() -> None:
    """Verifies legacy enum-based gzip bytes roundtrip."""
    content = b"artifact payload for gzip roundtrip"

    compressed_content = compress_bytes(content, CompressionAlgorithm.GZIP)

    assert CompressionAlgorithm.GZIP in SUPPORTED_COMPRESSION_ALGORITHMS
    assert compressed_content != content
    assert decompress_bytes(compressed_content, CompressionAlgorithm.GZIP) == content


def test_gzip_path_roundtrip(tmp_path: Path) -> None:
    """Verifies legacy enum-based gzip path roundtrip."""
    content = b"artifact payload written through gzip file helpers"
    destination_path = tmp_path / "artifact.json.gz"

    written_path = write_compressed_bytes(destination_path, content, CompressionAlgorithm.GZIP)

    assert written_path == destination_path
    assert destination_path.exists()
    assert read_compressed_bytes(destination_path, CompressionAlgorithm.GZIP) == content


# New Literal & zstd test cases
def test_gzip_compression_roundtrip() -> None:
    """Verifies that gzip compression and decompression roundtrips correctly."""
    data = b"Hello world! This is a test of the gzip compression flow."
    compressed = compress_bytes(data, method="gzip")
    assert compressed.startswith(GZIP_MAGIC)
    decompressed = decompress_bytes(compressed, method="gzip")
    assert decompressed == data


def test_raw_compression_roundtrip() -> None:
    """Verifies that raw method returns unmodified bytes."""
    data = b"Hello raw world!"
    compressed = compress_bytes(data, method="raw")
    assert compressed == data
    decompressed = decompress_bytes(compressed, method="raw")
    assert decompressed == data


def test_zstd_compression_error_when_missing() -> None:
    """Verifies that zstd compression fails loudly when zstandard is not installed."""
    data = b"Some data to compress with missing zstd"
    with (
        patch("factory.artifacts.compression.HAS_ZSTD", False),
        pytest.raises(ImportError, match="Cannot compress with zstd"),
    ):
        compress_bytes(data, method="zstd")


def test_zstd_decompression_error_when_missing() -> None:
    """Verifies that trying to decompress zstd data without the module raises ImportError."""
    zstd_data = GZIP_MAGIC + b"gzip-looking data is still not zstd"
    with patch("factory.artifacts.compression.HAS_ZSTD", False):
        with pytest.raises(ImportError) as excinfo:
            decompress_bytes(zstd_data, method="zstd")
        assert "Cannot decompress zstd-compressed data" in str(excinfo.value)


@patch("factory.artifacts.compression.HAS_ZSTD", True)
def test_zstd_compression_mocked() -> None:
    """Verifies that zstd compression and decompression work when zstandard is mocked."""
    data = b"Mocked zstd data"
    mock_zstandard = MagicMock()
    mock_compressor = MagicMock()
    mock_decompressor = MagicMock()

    mock_compressor.compress.return_value = ZSTD_MAGIC + b"compressed"
    mock_decompressor.decompress.return_value = data

    mock_zstandard.ZstdCompressor.return_value = mock_compressor
    mock_zstandard.ZstdDecompressor.return_value = mock_decompressor

    with patch("factory.artifacts.compression.zstandard", mock_zstandard):
        compressed = compress_bytes(data, method="zstd")
        assert compressed.startswith(ZSTD_MAGIC)
        mock_compressor.compress.assert_called_once_with(data)

        decompressed = decompress_bytes(compressed, method="zstd")
        assert decompressed == data
        mock_decompressor.decompress.assert_called_once_with(compressed)


def test_read_write_compressed_artifact(tmp_path: Path) -> None:
    """Tests writing and reading back compressed artifacts with auto-detection."""
    data = b"Artifact data to be written to file system."
    file_path = tmp_path / "artifact.gz"

    # Write as gzip
    write_compressed_artifact(file_path, data, method="gzip")
    assert file_path.exists()

    # Read back and check auto-detect (by signature)
    read_data = read_compressed_artifact(file_path)
    assert read_data == data

    # Test auto-detect by extension fallback
    raw_path = tmp_path / "artifact_raw.txt"
    with open(raw_path, "wb") as f:
        f.write(data)
    assert read_compressed_artifact(raw_path) == data

    # Test missing file
    with pytest.raises(FileNotFoundError):
        read_compressed_artifact(tmp_path / "nonexistent.json")
