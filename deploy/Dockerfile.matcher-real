# Real-matcher Nitro EIF: por.PlainMatcher on loopback :8080, fronted by
# attested-workload app-proxy over attested TLS.
#
# Build context: run ./assemble-matcher-eif.sh (or copy artifacts manually):
#   bountynet-bin   <- attested-workload (deploy/build-bountynet-bin.sh)
#   app/por/        <- sphinx-tahoe/por
#   app/run_matcher.py
#   entry-matcher.sh
#
#   docker build -t matcher-real .
#   nitro-cli build-enclave --docker-uri matcher-real:latest --output-file matcher.eif
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal
RUN dnf install -y python3 python3-pip iproute && dnf clean all
RUN pip3 install --no-cache-dir cryptography
COPY bountynet-bin /usr/local/bin/bountynet
COPY app/ /app/
COPY entry-matcher.sh /entry-matcher.sh
RUN chmod +x /entry-matcher.sh
CMD ["/entry-matcher.sh"]
