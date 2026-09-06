Smoke tests for Graylog runtime

Files:

- `check-graylog-alive.sh` — checks `/api/system/lbstatus` returns `ALIVE`.
- `send-graylog-test-message.sh` — emits a RFC5424-like syslog line to the local
  rsyslog TCP input (`127.0.0.1:10514`) which should be forwarded to Graylog.
- `query-graylog-search.sh` — example script to query Graylog 7.x Search/Messages
  API; requires valid admin credentials or API token.

Usage examples:

```bash
# on the graylog-stack host (or via SSH)
./scripts/smoke/check-graylog-alive.sh 127.0.0.1 9000
./scripts/smoke/send-graylog-test-message.sh "smoke test from $(hostname)"
# then query (replace admin:password or use API token)
./scripts/smoke/query-graylog-search.sh 127.0.0.1 9000 "message:graylog-smoke-test"
```

Notes:

- `query-graylog-search.sh` uses `GRAYLOG_ROOT_PASSWORD` if present and queries
  `/api/views/search/messages`, which is compatible with the current Graylog 7.x
  stack in this repo.
- The helper is best for simple Lucene-style query strings without embedded
  quotes. For more complex searches, use `curl` with a JSON body directly.
- These scripts are intentionally light-weight and intended for manual or CI
  smoke checks after `./with-secrets scripts/provision.sh --stack graylog-stack`.
