FROM python:3.13.3-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    imagemagick \
    ghostscript \
    sox \
    libsox-fmt-all \
    bash \
    curl \
    file \
    && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY policy.xml /etc/ImageMagick-6/policy.xml
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install \
    python-multipart \
    pillow \
    requests \
    numpy \
    opencv-python-headless \
    pydub
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]