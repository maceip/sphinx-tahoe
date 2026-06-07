"""Real Algorand adapter for x402 settlement (testnet via AlgoNode).

The injected production dependencies from tenet.x402 made concrete:
  - ``AlgodTxLookup`` resolves a txid to a confirmed on-chain transaction
    (used by x402.verify_payment),
  - ``pay_algo`` builds, signs, submits, and confirms a real ALGO payment.

Native ALGO is used for the demo (no ASA opt-in needed); USDC (ASA 31566704) is
the production asset and slots into the same ConfirmedTx shape.
"""

from __future__ import annotations

from algosdk import transaction
from algosdk.v2client import algod, indexer

from tenet.x402 import ConfirmedTx

ALGOD_TESTNET = "https://testnet-api.algonode.cloud"
INDEXER_TESTNET = "https://testnet-idx.algonode.cloud"
ALGOD_MAINNET = "https://mainnet-api.algonode.cloud"
INDEXER_MAINNET = "https://mainnet-idx.algonode.cloud"

# Common testnet USDC ASA for demos (users can override via env or arg).
# On Algorand testnet the "USDC" test asset is typically 10458941 (confirm in a dispenser if needed).
TESTNET_USDC_ASA = 10458941


def algod_client(address: str = ALGOD_TESTNET, token: str = "") -> algod.AlgodClient:
    return algod.AlgodClient(token, address)


def indexer_client(address: str = INDEXER_TESTNET, token: str = "") -> indexer.IndexerClient:
    return indexer.IndexerClient(token, address)


def pay_algo(
    client: algod.AlgodClient,
    private_key: str,
    sender: str,
    receiver: str,
    micro_algos: int,
    *,
    note: bytes | None = None,
    wait_rounds: int = 8,
) -> str:
    """Submit a real native-ALGO payment and wait for confirmation. Returns txid."""
    params = client.suggested_params()
    txn = transaction.PaymentTxn(sender, params, receiver, int(micro_algos), note=note)
    signed = txn.sign(private_key)
    txid = client.send_transaction(signed)
    transaction.wait_for_confirmation(client, txid, wait_rounds)
    return txid


def pay_asset(
    client: algod.AlgodClient,
    private_key: str,
    sender: str,
    receiver: str,
    asset_id: int,
    amount: int,
    *,
    note: bytes | None = None,
    wait_rounds: int = 8,
) -> str:
    """Submit a real ASA transfer (e.g. testnet USDC) and wait for confirmation. Returns txid."""
    params = client.suggested_params()
    txn = transaction.AssetTransferTxn(sender, params, receiver, int(amount), asset_id, note=note)
    signed = txn.sign(private_key)
    txid = client.send_transaction(signed)
    transaction.wait_for_confirmation(client, txid, wait_rounds)
    return txid


class AlgodTxLookup:
    """Resolves a txid to a ConfirmedTx. Tries the indexer, then algod pending info.

    This is the ``tx_lookup`` callable injected into ``tenet.x402.verify_payment``.
    """

    def __init__(
        self,
        idx: indexer.IndexerClient | None = None,
        algod_c: algod.AlgodClient | None = None,
    ) -> None:
        self._idx = idx if idx is not None else indexer_client()
        self._algod = algod_c if algod_c is not None else algod_client()

    def __call__(self, tx_id: str) -> ConfirmedTx | None:
        tx = self._from_indexer(tx_id)
        if tx is not None:
            return tx
        return self._from_algod_pending(tx_id)

    def _from_indexer(self, tx_id: str) -> ConfirmedTx | None:
        try:
            resp = self._idx.transaction(tx_id)
        except Exception:
            return None
        return _parse_tx(resp.get("transaction", {}))

    def _from_algod_pending(self, tx_id: str) -> ConfirmedTx | None:
        try:
            info = self._algod.pending_transaction_info(tx_id)
        except Exception:
            return None
        txn = info.get("txn", {}).get("txn", {})
        confirmed = int(info.get("confirmed-round", 0) or 0)
        # algod pending uses raw msgpack field names
        if txn.get("type") == "pay":
            return ConfirmedTx(
                sender=txn.get("snd", ""),
                receiver=txn.get("rcv", ""),
                amount=int(txn.get("amt", 0) or 0),
                asset=0,
                confirmed_round=confirmed,
            )
        return None


def _parse_tx(raw: dict) -> ConfirmedTx | None:
    if not raw:
        return None
    confirmed = int(raw.get("confirmed-round", 0) or 0)
    if raw.get("tx-type") == "pay":
        pay = raw.get("payment-transaction", {})
        return ConfirmedTx(
            sender=raw.get("sender", ""),
            receiver=pay.get("receiver", ""),
            amount=int(pay.get("amount", 0) or 0),
            asset=0,
            confirmed_round=confirmed,
        )
    if raw.get("tx-type") == "axfer":
        axfer = raw.get("asset-transfer-transaction", {})
        return ConfirmedTx(
            sender=raw.get("sender", ""),
            receiver=axfer.get("receiver", ""),
            amount=int(axfer.get("amount", 0) or 0),
            asset=int(axfer.get("asset-id", 0) or 0),
            confirmed_round=confirmed,
        )
    return None
