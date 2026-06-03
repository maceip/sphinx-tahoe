# Enclave plane — attested-workload integration

**Engine:** [attested-workload](https://github.com/maceip/attested-workload) @ `79a5ea2`  
**Deploy:** `deploy/README.md`, `DEPENDENCIES.md`  
**Threat model:** `docs/matcher_threat_model.md`  
**Live validation:** `deploy/HARDWARE_VALIDATION_2026-06-03.md`, `STATUS.md`

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

After Let's Encrypt, the leaf cert has no CMW extension; `aw check` falls back to
`GET /eat` and uses the EAT re-bound to the LE cert SPKI (`79a5ea2`).

## Build & deploy

```bash
ATTESTED_WORKLOAD_SHA=79a5ea2 ./deploy/assemble-matcher-eif.sh
# on Nitro instance:
cd deploy/eif-build && docker build -t matcher-real . && ...
./deploy/nitro-deploy.sh
# production TLS (when DNS for {value_x_prefix}.aeon.site points at parent):
sudo bountynet proxy --cid <cid> --acme
```

## Status (2026-06-03)

| Item | Status |
|------|--------|
| Quote verification (`aw check`) | **Live** — https://d851588d3b41.aeon.site/ |
| Client gate + SPKI pin (H3) | Done — unit tested |
| App-proxy `/v1/*` → loopback | Done — attested-workload `vsock.rs` |
| Oblivious matcher (H4) | Done — Python + tests |
| Fresh Nitro quote on EC2 | **Done** — eu-central-1, post-ACME rebind |
| Production TLS (Let's Encrypt) | **Done** — TLS-ALPN-01, CT verified |
| Engine consolidation | **Done** — single attested-workload pin |

## Legacy doc

Historical runcards/bountynet-genesis notes: `docs/enclave_plane_runcards.md`.
