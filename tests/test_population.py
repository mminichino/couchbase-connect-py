"""Tests for JSON Lines collection population."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from couchbase_connect.server import Server


class RecordingCollection:
    def __init__(self) -> None:
        self.documents: list[tuple[str, object]] = []

    def upsert(self, key: str, document: object) -> None:
        self.documents.append((key, document))


def test_populate_collection_uses_uuid_keys(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "documents.jsonl"
    source.write_text('{"name": "one"}\n\n{"name": "two"}\n', encoding="utf-8")
    collection = RecordingCollection()
    db = Server()
    monkeypatch.setattr(db, "ensure_collection", lambda *_: collection)

    imported = db.populate_collection(source, "bucket", "scope", "collection")

    assert imported == 2
    assert [document for _, document in collection.documents] == [
        {"name": "one"},
        {"name": "two"},
    ]
    assert all(UUID(key).version == 4 for key, _ in collection.documents)
