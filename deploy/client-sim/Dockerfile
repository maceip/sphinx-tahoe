FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.162

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

# System deps for Rust (tlsn crate) + general build.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain for tlsn 2PC test (verifier role in simulation client).
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

# Clone and build tlsn basic example as the 2PC test binary (verifier + prover).
# This gives the simulation client access to the tlsn crate for the pure test with min_mix_hops=3.
RUN git clone --depth 1 https://github.com/tlsnotary/tlsn.git /tmp/tlsn-src && \
    cd /tmp/tlsn-src && \
    cargo build --release --example basic && \
    cp target/release/examples/basic /usr/local/bin/tlsn-2pc-test && \
    chmod +x /usr/local/bin/tlsn-2pc-test && \
    rm -rf /tmp/tlsn-src /root/.cargo/registry /root/.cargo/git || true

# Primary path: pre-built static binary (produced by scripts/build_binary.py or CI).
# For development you can extend the build context or override the COPY to install
# the package from source using uv (see updated build-client-sim-image.sh).
COPY dist/tenet-linux-x86_64 /usr/local/bin/tenet || true
COPY config/live-enclave.json /etc/tenet/live-enclave.json || true
COPY config/join-pack.json /etc/tenet/join-pack.json || true
COPY config/live-mailbox-client.json /etc/tenet/live-mailbox-client.json || true
COPY deploy/client-sim/entrypoint.sh /usr/local/bin/tenet-client-entrypoint

RUN chmod +x /usr/local/bin/tenet /usr/local/bin/tenet-client-entrypoint /usr/local/bin/tlsn-2pc-test 2>/dev/null || true \
  && mkdir -p /var/lib/tenet-client /var/log/tenet-client /workspace

ENV JOIN_PACK=/etc/tenet/join-pack.json \
    POR_TIMEOUT=120 \
    PROMPT=Monet \
    TENET_CLIENT_ID=client-sim-1 \
    TENET_NAT_PROFILE=nat \
    TENET_CONTEXT_DIR=/var/lib/tenet-client/context \
    TENET_LOG_DIR=/var/log/tenet-client

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/tenet-client-entrypoint"]
CMD ["ask"]
