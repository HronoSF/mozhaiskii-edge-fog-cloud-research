ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive
COPY apt.preferences /etc/apt/preferences.d/ehu-scheduling-baseline
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3=3.12.3-0ubuntu2.1 iproute2=6.1.0-1ubuntu6.4 iputils-ping=3:20240117-1ubuntu0.1 iperf3=3.16-1build2 \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/bin/sleep"]
CMD ["infinity"]
