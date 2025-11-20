FROM ubuntu:jammy
ENV DEBIAN_FRONTEND=noninteractive
ARG ARCH=amd64

# Install required packages
RUN apt-get update && \
    apt-get install -y \
        unzip \
        iproute2 \
        iptables \
        curl \
        wget \
        iputils-ping \
        net-tools && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

# Copy local tun2socks archive into the image
COPY tun2socks-linux-${ARCH}.zip /tun2socks-linux-${ARCH}.zip

# Install tun2socks from local archive
RUN unzip /tun2socks-linux-${ARCH}.zip && \
    mv tun2socks-linux-${ARCH} /usr/local/bin/tun2socks && \
    chmod +x /usr/local/bin/tun2socks

# Copy startup script
COPY main.sh /main.sh
RUN chmod +x /main.sh

CMD ["/main.sh"]
