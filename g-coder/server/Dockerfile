FROM gentoo/stage3:amd64-openrc

RUN echo 'dev-lang/kotlin-bin' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/fastapi' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/annotated-doc' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/aiosqlite' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/pwdlib' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/pydantic-extra-types' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/pydantic-settings' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/strawberry-graphql' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-python/sqlmodel' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'app-shells/nushell' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'app-shells/fish' >> /etc/portage/package.accept_keywords/keywords
RUN echo 'dev-dotnet/libgdiplus cairo' >> /etc/portage/package.use/use
RUN getuto
RUN emerge --sync
RUN emerge app-eselect/eselect-repository
RUN eselect repository enable guru
RUN emerge --sync guru
RUN emerge --getbinpkg --update --deep --newuse @world
RUN emerge --getbinpkg --noreplace \
    app-shells/nushell \
    app-shells/fish \
    dev-python/pip \
    dev-python/ffmpeg-python \
    dev-python/pillow \
    dev-python/requests \
    dev-python/uvicorn \
    dev-python/fastapi \
    dev-python/aiohttp \
    dev-python/aiofiles \
    dev-python/python-dotenv \
    dev-lang/go \
    dev-lang/rust-bin \
    dev-lang/ruby \
    dev-lang/lua \
    dev-lang/mono \
    dev-lang/nim \
    dev-lang/zig-bin \
    dev-lang/php \
    dev-lang/kotlin-bin \
    dev-lang/typescript \
    dev-java/openjdk-bin \
    app-portage/gentoolkit \
    net-misc/wget \
    net-misc/yt-dlp \
    net-libs/nodejs \
    app-misc/jq \
    app-misc/fastfetch \
    media-video/ffmpeg \
    media-gfx/imagemagick \
    media-sound/sox \
    media-libs/vips


RUN groupadd -g 1000 gcoder && useradd -r -u 1000 -g gcoder -m -d /home/gcoder gcoder
RUN npm install -g ts-node mathjs imagescript
ENV NODE_PATH=/usr/local/lib/node_modules
RUN mkdir -p /app && \
    chown -R root:root /app && \
    chmod -R 555 /app
COPY --chown=gcoder:gcoder . /app

USER gcoder
EXPOSE 8000

CMD ["bash", "-c", "uvicorn --app-dir /app app:app --host 0.0.0.0 --port 8000"]
