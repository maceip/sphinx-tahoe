# Supernode Reachability — Threat Model & Constraints

Status: **review required before code merge**. This document must be approved
by security review before supernode forwarding code lands on main.

## What a supernode is

A supernode is a regular P-OR node (same binary) with a **public IP** that
also forwards UDP packets for registered peers who cannot accept inbound
connections (NAT'd experts).

The supernode is a **reachability relay only**. It forwards opaque encrypted
bytes. It does not decrypt, parse, or inspect Outfox packets, circuit packets,
prompts, envelopes, or provider metadata.

## What a supernode is NOT

- Not a mix node (no batching, delay, or cover traffic at the relay layer)
- Not a trusted intermediary (all forwarded bytes are encrypted end-to-end)
- Not a NAT hole-punching server (no STUN/TURN/ICE)
- Not an eBPF/XDP accelerator (user-space UDP only)

## Threat model

### Adversary capabilities

| Adversary | Can see | Cannot see |
|---|---|---|
| Supernode operator | Source IP of both client and expert, packet timing, packet sizes | Packet contents (encrypted), prompt text, expert identity beyond peer_id |
| Network observer (same LAN as supernode) | All of the above | Same |
| Client | Supernode IP, expert's peer_id from directory | Expert's real IP (behind NAT, via supernode) |
| Expert | Supernode IP, nothing about client | Client IP (supernode is the visible source) |

### What the supernode CAN correlate

**This is the critical risk:**

1. **Client ↔ Expert timing**: The supernode sees a forward packet arrive from
   client IP A, and immediately forwards it to expert IP B. The temporal
   correlation is trivial. This is inherent to inline forwarding without mixing
   delays.

2. **Session linking**: All packets for the same registered peer go through the
   same supernode. The supernode can count packets, measure session duration,
   and link forward + return traffic for the same session.

3. **Reachability + mix on same IP**: If a supernode also serves as an Outfox
   relay hop on the mix path AND as the reachability forwarder, the supernode
   sees both the mix-layer traffic and the forwarded traffic. This makes
   correlation strictly easier than if they were separate roles on separate IPs.

### What the supernode CANNOT do

1. **Read prompts or responses** — all traffic is Outfox-encrypted or circuit-encrypted
2. **Modify traffic undetected** — AEAD on forward path, magic check on return
3. **Impersonate the expert** — needs expert's KEM secret key
4. **Learn which frontier model is called** — provider selection is inside the encrypted envelope

## Constraints (security team mandated)

1. **Reachability relay is opaque** — `SupernodeForwarder` must NEVER parse
   packet contents beyond the type byte (0x00/0x01) needed for forwarding.

2. **Separate reachability from mix role** — document that running reachability
   relay + mix relay on the same public IP creates a correlation surface. MVP
   may allow it with a warning; production should separate.

3. **Client dials trusted relay endpoints only** — the client config or
   directory must specify which supernodes to trust. No auto-discovery of
   random supernodes.

4. **Directory embeds signed PeerAddressRecord** — the record must be signed
   by the supernode's key. Client verifies before dialing.

5. **Registration requires challenge-response** — already implemented in
   `PeerAddressRelay`. Prevents spoofed registrations.

6. **Heartbeat TTL enforced** — expired peers become unreachable. Already
   implemented.

## Explicitly deferred

- **Automated directory registration** — supernodes registering themselves in
  the public directory without operator approval
- **Direct UDP** — client connecting directly to expert's NAT'd address via
  hole-punching. Relay-first is the correctness path.
- **Mixing reachability traffic** — adding batching/delay at the supernode
  forwarding layer (would add latency, not in scope for MVP)
- **Multiple supernodes per expert** — failover between supernodes

## Implementation order (per security team)

0. This threat model doc (approved before code merge)
1. Opaque inline forward (SupernodeForwarder) — done, pending review
2. Client dial to trusted relay endpoints from config/directory
3. Directory embeds signed PeerAddressRecord
4. Bootstrap defaults with explicit trust story
5. Security regression tests (not just happy path)
