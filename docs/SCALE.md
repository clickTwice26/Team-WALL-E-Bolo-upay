# Integration path and scale

How Bolo upay would plug into upay's wallet, how it runs on several CPU
cores, what it measured under load, and what changes for production.

## 1. The wallet adapter: one class to replace

Money moves only through `api/app/wallet/`. The API and the risk code see a
small `WalletAdapter` protocol and nothing else:

| Method | Returns |
|---|---|
| `balance(uid)` | the user's balance |
| `history(uid)` | transactions, oldest first (the risk features read this) |
| `transfer(uid, intent, phone, amount, idempotency_key)` | `{id, ts, balance, replayed}`; raises `InsufficientFunds` or `WalletUnavailable` |

| `WALLET_ADAPTER` | Class | What it is |
|---|---|---|
| `local` (default) | `LocalWallet` | Today's SQLite ledger (`users.balance`, `transactions`) |
| `mock_upay` | `MockUpaySandbox` | A stand-in for upay's API: every call waits `MOCK_UPAY_LATENCY_MS` (default 120 ms, ±50%) and fails at `MOCK_UPAY_FAILURE_RATE` (default 2%). Half the failed transfers are lost requests (nothing moved), half are lost responses (the money moved but we never heard back) |

A pilot with upay adds one class, say `UpayWallet`, that calls upay's real
API with the same three methods, and sets `WALLET_ADAPTER=upay`. The parser,
the risk model, the interview, the PIN guard and the biometric check do not
change: `tests/test_wallet.py` runs the same risky payment through both
adapters and checks that the level, probability, hard rules and features
are identical. A wallet outage is a `503 wallet_unavailable`, never a GREEN.

## 2. Idempotency: a retried tap never sends twice

Two layers, because a payment can be retried for two different reasons:

1. **The client's retry.** `POST /api/execute` accepts an `Idempotency-Key`
   header (8 to 100 characters). The first completed response for a
   (user, key) pair is stored; the same key again returns that response
   unchanged, even after the assessment is marked executed. Only completed
   transfers are remembered, so after a wrong PIN or an unfinished hold the
   user retries with the same key. The same key for a different transfer is
   refused (`422 idempotency_key_reused`).
2. **Our retry towards the wallet.** The key we send to the wallet is the
   assessment id: one risk check, at most one transfer. If upay times out
   after moving the money, the assessment stays open; the retry reaches the
   wallet with the same key and gets the original transfer back.

`LocalWallet` takes SQLite's write lock (`BEGIN IMMEDIATE`) before it reads
the balance, so two workers can never both see enough money and both send.
Tested: same key twice, a key reused for another transfer, a wrong PIN then
the right one with the same key, four parallel retries (one transfer), and
the sandbox losing the request or the response.

## 3. Workers and the database

| What | How |
|---|---|
| Processes | `gunicorn` with `uvicorn_worker.UvicornWorker` × `WEB_CONCURRENCY` (default: CPU count), `api/gunicorn.conf.py`, started by `deploy/Dockerfile` |
| Model | Each worker loads the risk model and its SHAP explainer once at startup (FastAPI lifespan), not on its first request, and predicts on one OpenMP thread (`OMP_NUM_THREADS=1`) |
| Database | One SQLite file shared by all workers: WAL journal (readers never wait for the writer), `busy_timeout` 15 s (a writer waits instead of failing "database is locked"), `synchronous=NORMAL`, one connection per request thread. The first worker to open a new file seeds it inside `BEGIN IMMEDIATE`, so seeding happens once |
| Session key | Every worker must sign tokens with the same key. Set `AUTH_SECRET`; if it is missing, `gunicorn.conf.py` makes one random key in the master process before the workers start (sessions then end on restart, as before) |
| Metrics | Prometheus text at `/metrics` (`prometheus-fastapi-instrumentator`), summed over all workers through `PROMETHEUS_MULTIPROC_DIR`. Registered before the web app's catch-all route. Caddy and the nginx site answer `/metrics` with 404, so only the internal network can scrape it |

**Why no Redis.** The plan listed Redis for PIN-limit counters and nonces.
Everything a worker must share already lives in the database all workers
use: the PIN guard (`pin_guard`), the one-time biometric challenge (stored
with its assessment), assessment status, idempotency keys, support chats and
TTS cache files. No state is kept in one worker's memory, so a request can
land on any worker. Redis would add a second store to secure and back up
without fixing anything at this size.

**When SQLite stops being enough.** One machine, one writer at a time. The
benchmark below shows writes are not the bottleneck at 500 virtual users;
the next limits are a second server (SQLite cannot be shared over the
network) and backups with point-in-time recovery. Then:

## 4. Production path: Postgres (not implemented)

1. `DATABASE_URL=postgresql+psycopg://...`; `store.py` moves to SQLAlchemy
   Core with the same function names, so callers do not change. Tests keep
   SQLite (`sqlite://` URL).
2. Alembic migrations replace `CREATE TABLE IF NOT EXISTS`; the first
   revision is today's schema.
3. `BEGIN IMMEDIATE` becomes `SELECT ... FOR UPDATE` on the user's balance
   row; idempotency tables keep their primary keys (unique constraints).
4. A `postgres` service in `docker-compose.yml` on an encrypted volume,
   with daily base backups and WAL archiving.
5. Then several app servers behind the load balancer; still no Redis, for
   the reason above.

With upay itself holding the ledger (`UpayWallet`), our database keeps only
risk checks, decisions, feedback and support chats.

## 5. Benchmark

**Setup.** `loadtest/flow.js` (k6) runs the app's payment flow: each virtual
user signs in once (bcrypt PIN check; a session lasts 30 minutes), then loops
parse → assess → execute (PIN, `Idempotency-Key`) with 1 s of think time
between steps, Tk 1 to a saved contact, users u1..u3. 15 s ramp-up, then 60 s
at full load. No LLM (`LLM_PROVIDER` empty), `WALLET_ADAPTER=local`,
`HOLD_SECONDS=0`, `DEMO_MODE=true`; `setup()` resets the demo data.

**Machine.** Local Mac: Apple M4, 10 cores, 16 GB. gunicorn with 10 workers
(the CPU count) and k6 in Docker Desktop on the same machine
(`docker run grafana/k6`, through `host.docker.internal`). Other jobs were
running on the machine at the same time (load average 50 to 80 during the
runs), so treat the numbers as a lower bound for a dedicated 10-core server;
a repeat of the 200-user run gave assess p95 337 ms instead of 582 ms.

Full flow (times in ms, p50 / p95 / p99):

| Virtual users | parse | **assess** | execute (PIN) | login (PIN) | Errors | Requests/s |
|---|---|---|---|---|---|---|
| 50 | 2 / 5 / 20 | **10 / 20 / 65** | 216 / 346 / 940 | 257 / 313 / 330 | 0% of 3,226 | 41 |
| 200 | 7 / 194 / 472 | **123 / 582 / 1,174** | 5,412 / 6,468 / 6,801 | 2,807 / 6,320 / 6,724 | 0% of 4,993 | 62 |
| 500 | 230 / 5,778 / 7,938 | **1,416 / 8,923 / 10,713** | 9,562 / 14,935 / 17,804 | 8,018 / 14,860 / 16,028 | 0% of 6,634 | 76 |

Risk check alone (`NO_EXECUTE=1`: parse → assess → cancel, no PIN after sign-in):

| Virtual users | parse | **assess** | login (PIN) | Errors | Requests/s |
|---|---|---|---|---|---|
| 200 | 2 / 19 / 83 | **10 / 70 / 259** | 348 / 425 / 462 | 0% of 13,768 | 175 |
| 500 | 21 / 877 / 2,234 | **202 / 2,483 / 3,556** | 9,822 / 12,526 / 13,374 | 0% of 23,074 | 293 |

**Reading it.**
- **Target (assess p95 < 300 ms without an LLM): met at 50 users (20 ms),
  and at 200 users when the PIN checks are taken out (70 ms). Not met at 200
  users in the full flow (582 ms, 337 ms on a repeat) or at 500 users.**
  No request failed in any run.
- The ceiling is the PIN check, not the risk model or the database. bcrypt
  (cost 12) takes about 170 ms of CPU per check on this machine, so 10 cores
  verify at most about 60 PINs a second. Every execute and every sign-in
  needs one, so above about 50 users the CPU is full of PIN checks and
  everything else queues behind them (500 users signing in during the 15 s
  ramp is 85 CPU-seconds of bcrypt alone). bcrypt is meant to be slow; the
  answers are more cores per server or more servers, not a weaker hash. In a
  real integration upay verifies the PIN on its own side.
- Two fixes came out of the first runs. (1) The model's predict used one
  OpenMP thread per CPU in every worker, 100 threads on 10 cores: assess p95
  was 2.3 s at 50 users. `gunicorn.conf.py` now sets `OMP_NUM_THREADS=1`
  (p95 20 ms). (2) One SQLite connection shared by a worker's request
  threads mixed their transactions ("database is locked", 26% errors at 200
  users); `store.conn()` now opens one connection per thread (0 errors).

Run it yourself (DEMO_MODE must be on; use a fresh `DB_PATH`):

```bash
cd api && DEMO_MODE=true HOLD_SECONDS=0 AUTH_SECRET=$(openssl rand -hex 16) \
  DB_PATH=/tmp/bolo-load.db gunicorn -c gunicorn.conf.py app.main:app
docker run --rm -i -e BASE=http://host.docker.internal:8000 -e VUS=200 \
  grafana/k6 run - < loadtest/flow.js          # add -e NO_EXECUTE=1 for the risk check alone
```

CI runs the same script as a smoke test (5 users, 20 s, fails on any error).
Staging and production numbers are still to be measured on their servers.

## 6. LLM, privacy and production

The benchmark runs without an LLM: the rule parser and the risk model carry
the whole flow (the parser's measured accuracy was also rules only). Today
the optional LLM is Gemini over the internet. Production should use a local
model instead (Ollama or llama.cpp, with Qwen 2.5 3B or Gemma 2 2B as
candidates) plus redaction of phone numbers and names before any prompt,
because MFS data is sensitive and subject to Bangladesh Bank rules. A local
model also removes the network round trip from the latency budget; it needs
its own capacity test on the target hardware before it goes on the payment
path.
