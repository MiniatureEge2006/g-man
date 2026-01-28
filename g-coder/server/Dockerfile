FROM python:3.13.3-slim



RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    jq \
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
    && ln -s /opt/zig/zig /usr/local/bin/zig \
    && rm zig-x86_64-linux-0.14.1.tar.xz
RUN groupadd -g 1000 gcoder && useradd -r -u 1000 -g gcoder -m -d /home/gcoder gcoder
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && rm requirements.txt
RUN pip install numpy requests pillow typed-ffmpeg
RUN pip install --pre -U "yt-dlp[default,curl-cffi]"
RUN npm install -g typescript node ts-node @types/node mathjs imagescript deno
ENV NODE_PATH=/usr/local/lib/node_modules
USER gcoder
RUN mkdir -p /home/gcoder/input && \
    mkdir -p /home/gcoder/output

USER root
RUN mkdir -p /app && \
    chown -R root:root /app && \
    chmod -R 555 /app
COPY --chown=gcoder:gcoder . /app

USER gcoder
EXPOSE 8000

CMD ["bash", "-c", "uvicorn --app-dir /app app:app --host 0.0.0.0 --port 8000"]
