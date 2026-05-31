"""Minimal on-device self-test for the tenet native stack.

First Android milestone: prove the five cross-compiled native wheels load and
the crypto runs on a real device/emulator. Output goes to logcat; the harness
greps for the TENET markers.
"""

from __future__ import annotations


def selftest() -> bool:
    import msgpack
    import cffi  # noqa: F401  (pulls libffi)
    import nacl.bindings as nb
    import pyaes
    from pqcrypto.sign.ml_dsa_65 import generate_keypair, sign, verify

    # msgpack round-trip
    assert msgpack.unpackb(msgpack.packb({"tenet": 1})) == {"tenet": 1}
    print("TENET-SELFTEST msgpack ok", flush=True)

    # libsodium X25519 + AEAD via PyNaCl
    pk = nb.crypto_scalarmult_base(b"\x11" * 32)
    assert len(pk) == 32
    print("TENET-SELFTEST libsodium/x25519 ok", flush=True)

    # AES-CTR via pyaes (pure-Python; the Chaquopy-safe payload cipher on Android)
    ctr = pyaes.Counter(initial_value=0)
    ct = pyaes.AESModeOfOperationCTR(b"\x00" * 16, counter=ctr).encrypt(b"hello")
    assert len(ct) == 5
    print("TENET-SELFTEST aes-ctr/pyaes ok", flush=True)

    # ML-DSA-65 (PQClean via pqcrypto) sign/verify
    pub, sec = generate_keypair()
    sig = sign(sec, b"tenet")
    assert verify(pub, b"tenet", sig)
    print("TENET-SELFTEST ml_dsa_65 sign/verify ok", flush=True)

    return True


def main():
    print("TENET-NATIVE-STACK starting", flush=True)
    try:
        selftest()
        print("TENET-NATIVE-STACK-OK", flush=True)
    except Exception as exc:  # surface on logcat
        import traceback

        print("TENET-NATIVE-STACK-FAIL:", exc, flush=True)
        traceback.print_exc()
        raise
