FROM python:3.13.3-slim



RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    xz-utils \
    ffmpeg \
    imagemagick \
    sox \
    nodejs \
    npm \
    php \
    ruby-full \
    lua5.4 \
    golang \
    clang \
    gcc \
    g++ \
    make \
    cmake \
    mono-complete \
    bash \
    cargo \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LO https://ziglang.org/download/0.11.0/zig-linux-x86_64-0.11.0.tar.xz \
    && tar -xf zig-linux-x86_64-0.11.0.tar.xz \
    && mv zig-linux-x86_64-0.11.0 /opt/zig \
    && ln -s /opt/zig/zig /usr/local/bin/zig
RUN groupadd -g 1000 gcoder && useradd -r -u 1000 -g gcoder -m -d /home/gcoder gcoder
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install numpy requests pillow yt-dlp bgutil-ytdlp-pot-provider
RUN npm install -g typescript ts-node yarn
USER gcoder
RUN mkdir -p /home/gcoder && \
    cd /home/gcoder && \
    git clone --single-branch --branch 0.8.2 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git && \
    cd bgutil-ytdlp-pot-provider/server/ && \
    yarn install --frozen-lockfile && \
    npx tsc

WORKDIR /app

COPY . /app


RUN mkdir -p /app/executions && chown gcoder:gcoder /app/executions && chmod 775 /app/executions/
USER root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
USER gcoder

EXPOSE 8000

CMD ["/entrypoint.sh"]