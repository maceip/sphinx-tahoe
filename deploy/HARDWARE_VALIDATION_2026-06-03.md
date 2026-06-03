# Nitro hardware validation — 2026-06-03

**Instance:** `i-069a473107424b7df` (`tenet-matcher-nitro`, m5.xlarge, eu-central-1b)  
**Public IP:** `63.178.62.239`  
**Engine pin:** attested-workload `79a5ea2328f2b30192e57b53913355dcd5e0201e` (`79a5ea2`)  
**EIF PCR0:** `e420380c20ab4b6b1bea5ca98a0627607f0f6075bc376296a964299f8b59ae3fd953af4ea6b14c6d0a1ee4507dc497ff`  
**Runtime Value X:** `d851588d3b413cbf7513d9d5fa93d466b42ad1603e1c7fdfd408cfd635a7cf6882412ce99c8fbb3aeac197c3e6c5f361`

## Phase 1 — attested TLS (IP, pre-ACME)

```bash
aw check --json https://63.178.62.239/
# Quote binding: PASS, Quote signature: PASS, SPKI binding: PASS
# tls_spki_hash: 9a64d8ea9b3e933f0c7152f381492e2427e713116be3f09d7ff5f66e88934996
```

## Phase 2 — production TLS (domain + Let's Encrypt)

**Domain:** https://d851588d3b41.aeon.site/  
**DNS:** `d851588d3b41.aeon.site` A → `63.178.62.239` (and `*.aeon.site` for future Value X prefixes)  
**TLS:** Let's Encrypt (TLS-ALPN-01 via `bountynet proxy --acme`)  
**Post-ACME engine:** `79a5ea2` — EAT re-bound to LE cert SPKI; `/eat` fallback in `aw check`

```bash
aw check --json https://d851588d3b41.aeon.site/
# Quote binding: PASS, Quote signature: PASS, SPKI binding: PASS
# tls_spki_hash: b880512378622821deebd4cb395a82eae271069acd491b805940145c97d1eab1
# CT (SCTs): PASS (Let's Encrypt)

curl -s https://d851588d3b41.aeon.site/healthz
# {"ok": true, "schema": "por.plain_enclave_plane.health.v1"}
```

## App-proxy

Matcher workload on `127.0.0.1:8080`; enclave forwards `/v1/*` and `/healthz`.

## Deploy notes

| Issue | Fix |
|-------|-----|
| `memory 3500` fails (E39) | Allocator is 3072 MiB; use **2048** MiB |
| `bountynet proxy` on :443 | Run as **root** (`sudo`) |
| `--acme` permission denied as ec2-user | ACME path also needs root |
| Shallow git clone + short SHA | Use full SHA or clone without `--depth 1` |
| `aw check` fails after ACME on old binary | Install `aw` @ `79a5ea2` (EAT rebind + `/eat` fallback) |
| EC2 resolver caches stale DNS | Wait or flush; authoritative DNS must be correct first |

## Operational follow-ups

- Allocate **Elastic IP** before instance stop/start (current IP is ephemeral).
- Redeploy EIF when changing attested-workload pin or matcher workload tree (Value X changes).
