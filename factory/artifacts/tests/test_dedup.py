from pathlib import Path

from factory.artifacts.dedup import ContentAddressedStore, sha256_bytes


def test_content_addressed_store_deduplicates_identical_bytes(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "artifacts")
    content = b'{"artifact_type":"Example","value":1}'

    first_entry = store.put_bytes(content)
    second_entry = store.put_bytes(content)

    assert first_entry.sha256 == sha256_bytes(content)
    assert first_entry.path == second_entry.path
    assert not first_entry.existed
    assert second_entry.existed
    assert first_entry.path.read_bytes() == content
    assert store.manifest() == {first_entry.sha256: first_entry.path}
    assert len(list(store.root.iterdir())) == 1
