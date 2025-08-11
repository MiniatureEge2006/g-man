FROM python:3.13.3-slim



RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    xz-utils \
    ffmpeg \
    frei0r-plugins \
    imagemagick \
    sox \
    nodejs \
    openjdk-17-jdk-headless \
    kotlin \
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
    nim \
    libc6-dev \
    libssl-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LO https://ziglang.org/download/0.14.1/zig-x86_64-linux-0.14.1.tar.xz \
    && tar -xf zig-x86_64-linux-0.14.1.tar.xz \
    && mv zig-x86_64-linux-0.14.1 /opt/zig \
    && ln -s /opt/zig/zig /usr/local/bin/zig
RUN groupadd -g 1000 gcoder && useradd -r -u 1000 -g gcoder -m -d /home/gcoder gcoder
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install numpy requests pillow bgutil-ytdlp-pot-provider typed-ffmpeg
RUN pip install --pre -U "yt-dlp[default]"
RUN npm install -g typescript node ts-node @types/node mathjs
USER gcoder
RUN mkdir -p /home/gcoder/executions && \
    mkdir -p /home/gcoder/executions/input && \
    mkdir -p /home/gcoder/executions/output && \
    chmod 775 /home/gcoder/executions && \
    cd /home/gcoder && \
    git clone --single-branch --branch 1.2.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git && \
    cd bgutil-ytdlp-pot-provider/server/ && \
    npm install && \
    npx tsc

USER root
RUN mkdir -p /app && \
    chown -R root:root /app && \
    chmod -R 555 /app && \
    chmod -R 555 /home/gcoder/bgutil-ytdlp-pot-provider
COPY --chown=gcoder:gcoder . /app

USER gcoder
EXPOSE 8000

CMD ["bash", "-c", \
     "set -m; \
      (cd /home/gcoder/bgutil-ytdlp-pot-provider/server/ && node build/main.js) & \
      (cd /home/gcoder/executions && uvicorn --app-dir /app app:app --host 0.0.0.0 --port 8000) & \
      fg %1 || fg %2 || wait -n; \
      kill 0; \
      exit 1"]