FROM ubuntu:24.04
ARG TARGETARCH
ARG LEAN_VERSION=4.35.0-rc2
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl zstd bubblewrap python3 git \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in amd64) platform=linux ;; arm64) platform=linux_aarch64 ;; *) exit 1 ;; esac \
    && curl --fail --location --retry 3 "https://github.com/leanprover/lean4/releases/download/v${LEAN_VERSION}/lean-${LEAN_VERSION}-${platform}.tar.zst" -o /tmp/lean.tar.zst \
    && mkdir /opt/lean && tar --zstd -xf /tmp/lean.tar.zst --strip-components=1 -C /opt/lean \
    && rm /tmp/lean.tar.zst
RUN useradd --uid 10001 --create-home verifier
ENV PATH="/opt/lean/bin:${PATH}"
COPY check.py /opt/verifier/check.py
USER verifier
WORKDIR /work
ENTRYPOINT ["python3", "/opt/verifier/check.py"]
