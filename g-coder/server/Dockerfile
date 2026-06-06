FROM archlinux:latest


RUN pacman -Syu --noconfirm --needed \
    base-devel \
    git \
    pacman-contrib


RUN pacman -S --noconfirm --needed \
    nushell fish elvish \
    python-pip python-pillow python-requests uvicorn python-fastapi \
    python-aiohttp python-aiofiles python-dotenv python-pydantic python-pydantic-settings \
    ffmpeg lame opencore-amr flite opus libvpx libvorbis fribidi x264 x265 dav1d libfdk-aac \
    imagemagick sox libvips mesa libgdiplus cairo cups ghostscript \
    go rust ruby lua mono nim zig php nodejs npm openjdk-src kotlin \
    wget yt-dlp jq fastfetch libqalculate \
    nspr nss atk gtk3 libxkbcommon alsa-lib


RUN useradd -m -G wheel builduser && \
    echo "builduser ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

USER builduser
WORKDIR /tmp


RUN git clone https://aur.archlinux.org/yay.git && \
    cd yay && makepkg -si --noconfirm


RUN yay -S --noconfirm \
    python-sqlmodel \
    python-strawberry-graphql \
    python-aiosqlite \
    python-annotated-types \
    python-pwdlib


USER root
WORKDIR /

RUN userdel -r builduser && \
    paccache -rk0 && \
    rm -rf /var/cache/pacman/pkg/* /tmp/*


RUN groupadd -g 1000 gcoder && useradd -r -u 1000 -g gcoder -m -d /home/gcoder gcoder

RUN pip install --break-system-packages pyvips playwright python-multipart
RUN npm install -g ts-node mathjs imagescript

ENV NODE_PATH=/usr/lib/node_modules
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/lib/playwright

RUN mkdir -p $PLAYWRIGHT_BROWSERS_PATH
RUN playwright install && \
    chown -R root:root $PLAYWRIGHT_BROWSERS_PATH && \
    chmod -R 755 $PLAYWRIGHT_BROWSERS_PATH


RUN mkdir -p /app && \
    chown -R root:root /app && \
    chmod -R 555 /app

COPY --chown=gcoder:gcoder . /app

USER gcoder
EXPOSE 8000

CMD ["bash", "-c", "uvicorn --app-dir /app app:app --host 0.0.0.0 --port 8000"]
