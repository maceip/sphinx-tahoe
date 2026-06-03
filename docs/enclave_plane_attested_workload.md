# Enclave plane — attested-workload integration

**Engine:** [attested-workload](https://github.com/maceip/attested-workload) @ `e039216`  
**Deploy:** `deploy/README.md`, `DEPENDENCIES.md`  
**Threat model:** `docs/matcher_threat_model.md`

## Architecture (Nitro)

```
Client ── attested TLS:443 ──▶ [parent: bountynet proxy, TCP→vsock]
                                      │
                                      ▼ vsock
                               [enclave: attested TLS + app-proxy]
                                      │
                    /eat, /, KMS     │     /v1/*, /healthz
                                      ▼
                               127.0.0.1:8080  matcher (run_matcher.py)
```

TLS terminates **inside** the enclave. The parent only bridges ciphertext.

## Client trust flow

1. `aw check --json https://<host>/` — quote chain + channel binding + Value X
2. `EnclaveTrustPolicy` — approve Value X + platform (sphinx-tahoe policy)
3. Pin `tls_spki_hash` — subsequent matcher calls over attested TLS (H3)

Default verifier: `SubprocessAttestedWorkloadVerifier` (`por/enclave_attest.py`).

## Build & deploy

```bash
ATTESTED_WORKLOAD_SHA=e039216 ./deploy/assemble-matcher-eif.sh
# on Nitro instance:
cd deploy/eif-build && docker build -t matcher-real . && ...
./deploy/nitro-deploy.sh
```

## Status (2026-06-03)

| Item | Status |
|------|--------|
| Quote verification (`aw check`) | Done — attested-workload tests green |
| Client gate + SPKI pin (H3) | Done — unit tested |
| App-proxy `/v1/*` → loopback | Done — in attested-workload `vsock.rs` |
| Oblivious matcher (H4) | Done — Python + tests |
| Fresh Nitro quote on EC2 | Needs hardware run (not claimed here) |

## Legacy doc

Historical runcards/bountynet-genesis notes: `docs/enclave_plane_runcards.md`.
