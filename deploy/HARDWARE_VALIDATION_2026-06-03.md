# Nitro hardware validation — 2026-06-03

**Instance:** `i-069a473107424b7df` (`tenet-matcher-nitro`, m5.xlarge, eu-central-1b)  
**Public IP:** `63.178.62.239`  
**Engine pin:** attested-workload `e03921678055831e2f3bd24bda38ed4f53074a33`  
**EIF PCR0:** `e420380c20ab4b6b1bea5ca98a0627607f0f6075bc376296a964299f8b59ae3fd953af4ea6b14c6d0a1ee4507dc497ff`  
**Runtime Value X:** `d851588d3b413cbf7513d9d5fa93d466b42ad1603e1c7fdfd408cfd635a7cf6882412ce99c8fbb3aeac197c3e6c5f361`

## Verified from Mac (fresh quote)

```bash
aw check --json https://63.178.62.239/
# Quote binding: PASS, Quote signature: PASS, SPKI binding: PASS
# tls_spki_hash: 9a64d8ea9b3e933f0c7152f381492e2427e713116be3f09d7ff5f66e88934996
```

## App-proxy

```bash
curl -sk https://63.178.62.239/healthz
# {"ok": true, "schema": "por.plain_enclave_plane.health.v1"}
```

## Deploy notes

| Issue | Fix |
|-------|-----|
| `memory 3500` fails (E39) | Allocator is 3072 MiB; use **2048** MiB |
| `bountynet proxy` on :443 | Run as **root** (`sudo`) |
| `--acme` permission denied as ec2-user | ACME path also needs root |
| Shallow git clone + short SHA | Use full SHA or clone without `--depth 1` |

## Client policy

Set `EnclaveTrustPolicy.approved_value_x` to the Value X above (not PCR0).
