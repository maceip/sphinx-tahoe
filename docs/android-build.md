# Android build guide (work in progress)

Goal: ship the node as a real on-device Android client, not only the
aarch64/Termux binary. This page collects the official build path and our
scoping decisions. It is a living doc — nothing here is wired into CI yet.

## Why this is now tractable

Two things changed the calculus:

1. **CPython has official Android support** (PEP 738, tier 3, since Python
   3.13). Targets: `aarch64-linux-android` (devices) and `x86_64-linux-android`
   (emulator). Minimum Android 5.0 / **API level 21**. The interpreter is no
   longer something we build by hand.
2. **PyPI accepts Android wheels** and **`cibuildwheel` 3.x can build them**
   (`--platform android`). So our native dependencies become a *wheel-build*
   problem, not bespoke `python-for-android` / NDK recipes.

Android wheel platform tags look like macOS tags — `android_21_arm64_v8a`,
`android_21_x86_64` — where the API level is the minimum the wheel was built
for, and a host with min-API `N` can install wheels tagged `N` or older.

## Scope: UDP-only v0 (the unlock)

The painful dependency is the QUIC stack (`aioquic` → `cryptography` →
Rust-for-Android). In this codebase that stack is **optional** — guarded behind
`AIOQUIC_AVAILABLE`; the core client / runtime / daemon path never imports it.

So **Android v0 = UDP-only client**, which drops `aioquic` (and its
`pylsqpack`/`h3` C stack). Verified: the `por` client + runtime import and the
packet crypto runs with only the four deps below — no `aioquic`. The set:

| Dep | Provides | Android build notes |
|-----|----------|---------------------|
| `pynacl` (libsodium) | X25519 KEM, ChaCha20-Poly1305 AEAD | libsodium has official `android-*.sh` scripts; pynacl is cffi over it |
| `msgpack` | wire serialization | single C module |
| `cryptography` | AES-CTR payload stream cipher (`se_enc`/`se_dec`) | **needs Rust** (`aarch64-linux-android` target); pyca + BeeWare mobile-forge have recipes |
| `pqcrypto` (PQClean) | ML-DSA-65 signatures on forward payloads | plain C, no deps; no upstream Android wheel → we build it |

Correction to an earlier note: `cryptography` is **not** QUIC-only — it backs
the AES-CTR payload cipher in `sphinxmix/OutfoxParams.py`, so it stays and the
Rust-for-Android toolchain is required. (A future option is swapping AES-CTR for
a libsodium ChaCha20 stream to drop the Rust dep — a wire-format change, out of
scope for v0.) `pqcrypto` remains the one dep with no existing Android recipe.
v1 adds the QUIC transport + native APK polish.

## Toolchain prerequisites

- Linux or macOS build host (Windows cannot cross-build CPython for Android).
- Android SDK command-line tools → set `ANDROID_HOME`. `android.py` /
  `cibuildwheel` install the matching NDK via `sdkmanager` automatically.
- Python 3.13+ on the build host.

```sh
# SDK (cmdline-tools) — one-time
#   download from https://developer.android.com/studio, then:
export ANDROID_HOME=/path/to/android-sdk   # contains cmdline-tools/latest
```

## Step A — CPython for Android

Two options.

**A1. Prebuilt (preferred to start):** use a `python-build-standalone` Android
runtime or BeeWare's Android Python. Fastest way to get an interpreter + stdlib.

**A2. From the CPython source tree** (`Android/android.py`) when we need a
specific version/config:

```sh
# in a CPython 3.13+ checkout, from Android/
./android.py configure-build && ./android.py make-build   # host python
./android.py build aarch64-linux-android                  # target python
./android.py package aarch64-linux-android                # -> cross-build/<HOST>/dist tarball
# emulator target:
./android.py build x86_64-linux-android
# run the testbed against a managed emulator:
./android.py test --managed maxVersion
```

## Step B — native deps as Android wheels

Build the three C deps with `cibuildwheel` (host: Linux x86_64 or macOS):

```sh
pip install "cibuildwheel>=3"
# per dependency source tree (or a small build repo that depends on them):
CIBW_PLATFORM=android \
CIBW_ARCHS=arm64_v8a,x86_64 \
CIBW_BUILD="cp313-*" \
cibuildwheel --platform android --output-dir wheels/
```

- `pynacl`, `msgpack` may build directly; if libsodium isn't found, vendor it
  via libsodium's `dist-build/android-*.sh` and point pynacl's build at it.
- `pqcrypto` (PQClean) has no Android wheel upstream — this is the one we own.
  Confirm PQClean's C builds under the NDK (it has no external deps) and that
  the extension links against `libpython3.x.so` (Android requires explicit
  linkage of extension modules to libpython).

Track upstream: `cffi` / `msgpack` / `PyNaCl` are starting to publish Android
wheels as `cibuildwheel` Android support matures — prefer upstream wheels when
they appear and only self-build the gaps.

## Step C — assemble the client

Bundle = CPython-Android runtime + the three wheels + the pure-Python `por`
tree. Headless (no Kivy/UI), so distribution is a packaged runtime, not an SDL
app. Briefcase (BeeWare) can wrap this into an installable APK once Step B
wheels exist.

## CI plan

When Step B builds locally, add a `wheels-android` job (cibuildwheel) that
produces the three wheels as artifacts, then an assembly job. Until then the
`android` job in `build-binaries.yml` ships the functional aarch64/Termux
binary. Do **not** flip Android to "required" until an assembled bundle runs in
an emulator (`android.py test --managed`).

## Open questions / v1

- **QUIC on Android:** needs `cryptography` (Rust → `aarch64-linux-android`
  Rust target) + `aioquic`. Defer until UDP v0 works end-to-end.
- **APK vs runtime bundle:** Briefcase APK vs a `python-build-standalone`
  embed; decide once we have wheels.
- **Signing key generation on device:** confirm libsodium + PQClean RNG sources
  behave under Android's seccomp sandbox.

## References

- [PEP 738 – Adding Android as a supported platform](https://peps.python.org/pep-0738/)
- [CPython `Android/README.md` (3.14)](https://github.com/python/cpython/blob/3.14/Android/README.md)
- [Using Python on Android — docs.python.org](https://docs.python.org/3/using/android.html)
- [cibuildwheel — platforms (Android/iOS)](https://cibuildwheel.pypa.io/en/latest/platforms/)
- [cibuildwheel #1960 — Add support for Android and iOS](https://github.com/pypa/cibuildwheel/issues/1960)
- [PyPI now supports iOS and Android wheels](https://socket.dev/blog/pypi-now-supports-ios-and-android-wheels-for-mobile-python-development)

## Build status — verified on a real arm64 emulator (2026-05-31)

The full pipeline works end-to-end: cross-compile wheels → Briefcase → APK →
install + run on an `arm64-v8a` emulator under **Python 3.13**.

**Native wheels (cp313, arm64-v8a, API 21), all cross-compiled here:**

| dep | wheel builds | loads + runs on device |
|-----|--------------|------------------------|
| msgpack | ✅ | ✅ |
| pynacl (libsodium) | ✅ (libsodium built inside the toolchain) | ✅ X25519 verified on device |
| cffi (libffi) | ✅ (libffi built inside the toolchain) | ✅ |
| pyaes (pure-Python AES-CTR) | ✅ | ✅ AES-CTR verified on device |
| pqcrypto 0.4.0 (ml_dsa_65) | ⚠️ builds, but **wrong binary** | ❌ |

`pycryptodome` was dropped on Android: its bespoke `ctypes` `.so` loader is
broken by Chaquopy. The runtime falls back to `pyaes` (byte-identical AES-CTR).

**The one remaining blocker — pqcrypto cffi cross-compile.** pqcrypto compiles
its PQClean bindings with cffi's `ffi.compile()` inside a Hatchling build hook
(`compile.py`). That call does **not** honor cibuildwheel's Android cross-env —
it emits **Mach-O (host macOS)** `.so` files (`*.cpython-313-darwin.so`) inside
an Android-tagged wheel, so `import pqcrypto._sign.ml_dsa_65` fails on device.
Forcing `CC=<ndk>/aarch64-linux-android21-clang` via `CIBW_ENVIRONMENT` makes
the clang run but distutils still injects host (`-arch`/macOS-sysroot) flags the
Android clang rejects.

Next options to close it:
1. Make cffi's `ffi.compile()` use the cross sysconfig (e.g. set
   `_PYTHON_SYSCONFIGDATA_NAME`/`_PYTHON_HOST_PLATFORM` so distutils emits the
   Android EXT_SUFFIX + toolchain, the same mechanism that cross-compiles the
   setuptools-based wheels correctly), or
2. Patch `compile.py` to build the extensions with an explicit cross
   `distutils`/`setuptools` `Extension` (clear host `CFLAGS`, set the NDK
   `CC`/`AR`/sysroot), or
3. Compile the cffi-generated `.c` for each algorithm directly with the NDK
   clang into correctly-named Android `.so`.

## Blocker RESOLVED (2026-05-31) — pure-Python ML-DSA fallback

Closed via option 2: the runtime now falls back from `pqcrypto` to pure-Python
**`dilithium-py`** for ML-DSA-65, selected automatically when pqcrypto can't load
(Android). Both are FIPS 204 ML-DSA-65 with identical key/signature encodings,
so they are **wire-interoperable** — a dilithium-py client's signatures verify
under a PQClean node and vice versa (proven in `tests/test_ml_dsa_backends.py`).

**The APK now runs the complete tenet crypto stack on an arm64 emulator** under
Python 3.13 — logcat:

```
TENET-SELFTEST msgpack ok
TENET-SELFTEST libsodium/x25519 ok
TENET-SELFTEST aes-ctr/pyaes ok
TENET-SELFTEST ml_dsa_65 sign/verify ok
TENET-NATIVE-STACK-OK
```

Android dep set (UDP-only v0): cross-compiled C wheels `msgpack`, `pynacl`
(libsodium), `cffi` (libffi); pure-Python `pyaes` (AES-CTR) and `dilithium-py`
(ML-DSA-65). No Rust, no pqcrypto, no pycryptodome. pqcrypto's cffi cross-compile
remains a nice-to-have (native speed) but is no longer on the critical path.
