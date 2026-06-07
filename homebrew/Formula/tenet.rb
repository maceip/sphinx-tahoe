# Homebrew formula for the tenet CLI (non-cask / command-line only).
#
# This installs the prebuilt single-file binary from GitHub Releases.
# Non-cask: pure CLI tool, no .app bundle.
#
# Quick demo install (no tap needed):
#   brew install --formula https://raw.githubusercontent.com/mac/sphinx-tahoe/master/homebrew/Formula/tenet.rb
#
# Or set up a tap for `brew install tenet`:
#   brew tap <your-org>/tenet https://github.com/<your-org>/sphinx-tahoe
#   brew install tenet
#
# Supported (from the build-binaries workflow):
#   macOS arm64 (Apple Silicon), macOS x86_64 (Intel), Linux x86_64, Windows (via direct .exe)
#
# The binary is completely self-contained (PyInstaller one-file) and includes
# the full tenet client: `tenet ask`, `tenet sponsor` (Algorand voucher issuance),
# `tenet status`, etc. No Python or extra deps required on the target machine.

class Tenet < Formula
  desc "Privacy-preserving expert mixnet client (ask + sponsor payments rail)"
  homepage "https://github.com/mac/sphinx-tahoe"
  license "BSD-2-Clause"

  # We use a "live" style that pulls the latest release asset for the current platform.
  # For reproducible demos pin a specific version and update the urls/shas below.
  version "latest"

  on_macos do
    on_arm do
      url "https://github.com/mac/sphinx-tahoe/releases/latest/download/tenet-macos-arm64"
      sha256 :no_check   # In real releases, replace with the SHA from the release's SHA256SUMS
    end
    on_intel do
      url "https://github.com/mac/sphinx-tahoe/releases/latest/download/tenet-macos-x86_64"
      sha256 :no_check
    end
  end

  on_linux do
    url "https://github.com/mac/sphinx-tahoe/releases/latest/download/tenet-linux-x86_64"
    sha256 :no_check
  end

  def install
    bin.install Dir["tenet-*"].first => "tenet"
    # Make sure it's executable (the release artifact should already be, but be safe)
    chmod 0755, bin/"tenet"
  end

  def caveats
    <<~EOS
      The tenet CLI is now on your PATH.

      Quick smoke:
        tenet --help
        tenet sponsor --help     # issues unlinkable Algorand-backed vouchers
        tenet ask --help

      For the full hackathon demo (Algorand testnet custodial payments + USDC + voucher + live mixnet):
        uv run python -m sim demo-payments sim/scenarios/all-local-docker-small.yaml --netem

      Linuxbrew users get the same binary. Windows users: download the .exe directly from the Releases page.
    EOS
  end

  test do
    assert_match "tenet", shell_output("#{bin}/tenet --help")
  end
end
