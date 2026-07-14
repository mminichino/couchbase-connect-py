# couchbase-connect-py

Python helper for connecting to Couchbase Server or Capella through a unified interface, with cluster creation and bucket/scope/collection/index automation.

## Install

```bash
pip install .
```

## Quick start

```python
from couchbase_connect import CouchbaseConfig, resolve

# Couchbase Server
config = (
    CouchbaseConfig()
    .host("127.0.0.1")
    .with_username("Administrator")
    .with_password("password")
    .ssl(False)
    .bucket("demo")
)
db = resolve(config)
db.connect(config)
db.create_bucket("demo", quota=128, replicas=0)
db.create_primary_index()
db.disconnect()

# Capella (when capella.token is set)
capella = (
    CouchbaseConfig()
    .token("...")
    .project("my-project")
    .database("my-cluster")
    .user_email("user@example.com")
    .with_username("dbuser")
    .with_password("dbpass")
)
db = resolve(capella)
db.connect(capella)
```

## Context manager

```python
from couchbase_connect import CouchbaseConfig, open_connection

with open_connection(config) as db:
    db.upsert("doc-1", {"hello": "world"})
```

## Tests

```bash
# Unit tests
pytest -m "not server and not capella"

# Couchbase Server integration (Docker / testcontainers)
pytest -m server

# Capella integration (copy example property files under tests/resources/)
cp tests/resources/test.capella.2.properties.example tests/resources/test.capella.2.properties
# edit credentials, then:
pytest -m capella
```
