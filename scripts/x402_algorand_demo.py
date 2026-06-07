#!/usr/bin/env python3
"""LIVE x402-on-Algorand demo: a real testnet payment unlocks an anonymous token.

  GET /token  -> HTTP 402 + Algorand payment requirements
  pay on Algorand testnet (real tx)  -> resubmit with X-PAYMENT
  server verifies the on-chain payment -> returns a blind signature
  client finalizes -> a real, unlinkable rate-limit token

Setup:
  1. Fund a testnet account at https://bank.testnet.algorand.network/
  2. export TENET_ALGO_MNEMONIC="<25-word mnemonic of the funded account>"
  3. python3 scripts/x402_algorand_demo.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algosdk import account, mnemonic

from tenet.algorand import AlgodTxLookup, algod_client, indexer_client, pay_algo
from tenet.blind_rsa import IssuerKey
from tenet.rate_token import NullifierLedger, spend_token
from tenet.x402_http import X402Server, buy_token_over_x402

PRICE_MICRO_ALGOS = 100_000  # 0.1 testnet ALGO
NETWORK = "algorand-testnet"


def main() -> int:
    mn = os.environ.get("TENET_ALGO_MNEMONIC", "").strip()
    if not mn:
        print("Set TENET_ALGO_MNEMONIC to a funded testnet account's 25-word mnemonic.")
        print("Fund one at https://bank.testnet.algorand.network/")
        return 2
    payer_sk = mnemonic.to_private_key(mn)
    payer_addr = account.address_from_private_key(payer_sk)

    algod = algod_client()
    bal = algod.account_info(payer_addr).get("amount", 0)
    print(f"payer:   {payer_addr}")
    print(f"balance: {bal/1e6:.6f} ALGO")
    if bal < PRICE_MICRO_ALGOS + 1000:
        print(f"\nInsufficient balance. Fund {payer_addr} at")
        print("https://bank.testnet.algorand.network/ then re-run.")
        return 2

    # the pool treasury (receives payment). Set TENET_PAY_TO to land it in a wallet
    # you can watch (e.g. your Pera/NVL6 address); else a throwaway receiver.
    treasury_addr = os.environ.get("TENET_PAY_TO", "").strip() or account.generate_account()[1]
    print(f"pay-to:  {treasury_addr}")

    issuer = IssuerKey.generate(bits=2048)
    tx_lookup = AlgodTxLookup(indexer_client(), algod)
    server = X402Server(
        issuer=issuer, pay_to=treasury_addr, price_micro_algos=PRICE_MICRO_ALGOS,
        network=NETWORK, tx_lookup=tx_lookup,
    )
    server.start()
    print(f"x402 server: {server.base_url}\n")

    def pay_fn(reqs):
        print(f"[402] pay {reqs.amount/1e6:.3f} ALGO to {reqs.pay_to}")
        txid = pay_algo(algod, payer_sk, payer_addr, reqs.pay_to, reqs.amount,
                        note=b"x402:" + reqs.nonce.encode())
        print(f"[chain] confirmed txid={txid}")
        print(f"        https://lora.algokit.io/testnet/tx/{txid}")
        # wait for the indexer to catch up so server-side verification finds it
        for _ in range(20):
            if tx_lookup(txid) is not None:
                break
            time.sleep(1.0)
        return txid

    try:
        token, info = buy_token_over_x402(server.base_url, issuer.public, pay_fn=pay_fn, timeout=60)
        print(f"\n[token] received blind-signed anonymous token (payer on chain: {info['payer']})")
        ledger = NullifierLedger()
        nf = spend_token(issuer.public, token, ledger)
        print(f"[spend] token verifies + nullifier burned: {nf[:16]}…")
        print("\n✅ LIVE x402-on-Algorand: real payment unlocked an anonymous token.")
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
