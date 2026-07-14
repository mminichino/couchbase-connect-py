"""Best-effort document dump stream (N1QL substitute for Java DCP CouchbaseStream)."""

from __future__ import annotations

import gzip
import json
import logging
from datetime import timedelta
from typing import Any, Dict, Iterator, Optional, TextIO

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.n1ql import QueryScanConsistency
from couchbase.options import ClusterOptions, ClusterTimeoutOptions, QueryOptions

logger = logging.getLogger(__name__)


class CouchbaseStream:
    """Dump documents from a collection as JSON lines.

    Continuous DCP streaming is not available in the official Python SDK; dump-to-now
    uses N1QL as a best-effort substitute.
    """

    def __init__(
        self,
        hostname: str,
        username: str,
        password: str,
        bucket: str,
        ssl: bool = True,
        scope: str = "_default",
        collection: str = "_default",
    ) -> None:
        self.hostname = hostname
        self.username = username
        self.password = password
        self.bucket = bucket
        self.use_ssl = ssl
        self.scope = scope
        self.collection = collection
        self._cluster: Optional[Cluster] = None
        self._doc_count = 0
        self._started = False
        self._mode: Optional[str] = None

    def __enter__(self) -> "CouchbaseStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.stop()

    def _connect_string(self) -> str:
        prefix = "couchbases://" if self.use_ssl else "couchbase://"
        return f"{prefix}{self.hostname}"

    def _ensure_cluster(self) -> Cluster:
        if self._cluster is not None:
            return self._cluster
        auth = PasswordAuthenticator(self.username, self.password)
        timeout = ClusterTimeoutOptions(
            kv_timeout=timedelta(seconds=5),
            connect_timeout=timedelta(seconds=15),
            query_timeout=timedelta(seconds=120),
        )
        options = ClusterOptions(
            auth,
            timeout_options=timeout,
            enable_tls=bool(self.use_ssl),
        )
        connect_string = self._connect_string()
        try:
            self._cluster = Cluster.connect(connect_string, options)
        except Exception:
            self._cluster = Cluster(connect_string, options)
        return self._cluster

    def stream_documents(self) -> None:
        """Mark dump mode (N1QL) — called for Java API parity."""
        self._mode = "dump"
        self._ensure_cluster()

    def start_to_now(self) -> None:
        """Begin dump-from-beginning-to-now (N1QL SELECT)."""
        self._mode = "dump"
        self._started = True
        self._ensure_cluster()

    def start_from_now(self) -> None:
        raise NotImplementedError(
            "Continuous streaming from now (DCP) is not supported by the official "
            "Couchbase Python SDK. Use start_to_now() / documents() for a one-shot dump."
        )

    def documents(self) -> Iterator[Dict[str, Any]]:
        """Yield {metadata, document} dicts for the current keyspace dump."""
        for line in self.stream_data():
            yield json.loads(line)

    def stream_data(self) -> Iterator[str]:
        """Yield JSON lines: {"metadata":{"id":...},"document":...}."""
        if not self._started:
            self.start_to_now()
        cluster = self._ensure_cluster()
        keyspace = f"`{self.bucket}`.`{self.scope}`.`{self.collection}`"
        statement = f"SELECT META().id AS id, t.* FROM {keyspace} t"
        options = QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS)
        logger.debug("Streaming dump via N1QL: %s", statement)
        result = cluster.query(statement, options)
        for row in result.rows():
            if not isinstance(row, dict):
                continue
            doc_id = row.pop("id", None)
            # Rows may be nested under alias 't' depending on query engine.
            document = row.get("t") if "t" in row and isinstance(row.get("t"), dict) else row
            if isinstance(document, dict) and "id" in document and doc_id is None:
                doc_id = document.pop("id", None)
            payload = {
                "metadata": {"id": doc_id},
                "document": document,
            }
            self._doc_count += 1
            yield json.dumps(payload, separators=(",", ":"), default=str)

    def to_writer(self, writer: TextIO) -> None:
        self.stream_documents()
        self.start_to_now()
        for record in self.stream_data():
            writer.write(record + "\n")
        self.stop()

    def to_compressed_file(self, filename: str) -> None:
        try:
            with gzip.open(filename, "wt", encoding="utf-8") as handle:
                self.to_writer(handle)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            raise OSError(f"Can not stream to file {filename}") from exc

    def stop(self) -> None:
        if self._cluster is not None:
            try:
                self._cluster.disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.debug("stream disconnect: %s", exc)
            self._cluster = None
        self._started = False

    def get_count(self) -> int:
        return self._doc_count
