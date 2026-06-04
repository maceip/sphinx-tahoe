FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.162

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    iproute2 \
    iptables \
    jq \
    tini \
  && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

COPY dist/por-linux-x86_64 /usr/local/bin/por
COPY config/live-enclave.json /etc/por/live-enclave.json
COPY config/join-pack.json /etc/por/join-pack.json
COPY config/live-mailbox-client.json /etc/por/live-mailbox-client.json
COPY deploy/client-sim/entrypoint.sh /usr/local/bin/tenet-client-entrypoint

RUN chmod +x /usr/local/bin/por /usr/local/bin/tenet-client-entrypoint \
  && mkdir -p /var/lib/tenet-client /var/log/tenet-client /workspace

ENV JOIN_PACK=/etc/por/join-pack.json \
    POR_TIMEOUT=120 \
    PROMPT=Monet \
    TENET_CLIENT_ID=client-sim-1 \
    TENET_NAT_PROFILE=nat \
    TENET_CONTEXT_DIR=/var/lib/tenet-client/context \
    TENET_LOG_DIR=/var/log/tenet-client

WORKDIR /workspace
ENTRYPOINT ["tini", "--", "/usr/local/bin/tenet-client-entrypoint"]
CMD ["ask"]
