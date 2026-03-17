FROM gentoo/stage3:amd64-openrc

RUN echo 'dev-lang/kotlin-bin' >> /etc/portage/package.accept_keywords/accept_keywords
RUN echo 'dev-dotnet/libgdiplus cairo' >> /etc/portage/package.use/useflags
RUN getuto
RUN emerge --sync
RUN emerge --getbinpkg --update --deep --newuse @world
RUN emerge --getbinpkg --noreplace \
    dev-lang/python \
    dev-python/pip \
    dev-lang/go \
    dev-lang/rust-bin \
    dev-lang/ruby \
    dev-lang/lua \
    dev-lang/mono \
    dev-lang/nim \
    dev-lang/zig-bin \
    dev-lang/php \
    dev-lang/kotlin-bin \
    dev-vcs/git \
    dev-java/openjdk-bin \
    app-portage/gentoolkit \
    net-misc/curl \
    net-misc/wget \
    net-libs/nodejs \
    app-misc/jq \
    app-misc/fastfetch \
    media-video/ffmpeg \
    media-gfx/imagemagick \
    media-sound/sox


RUN groupadd -g 1000 gcoder && useradd -r -u 1000 -g gcoder -m -d /home/gcoder gcoder
COPY requirements.txt .
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt && rm requirements.txt
RUN pip install --break-system-packages numpy requests pillow typed-ffmpeg yt-dlp[curl-cffi,default] pyvips[binary]
RUN npm install -g typescript ts-node @types/node mathjs imagescript deno
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
