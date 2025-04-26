FROM python:3.13.3-slim


RUN groupadd -r gcoder && useradd -r -g gcoder -d /app -s /sbin/nologin gcoder

WORKDIR /app


RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    imagemagick \
    sox \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install numpy requests pillow
RUN npm install -g typescript ts-node


COPY app.py .


RUN mkdir -p /app/executions && chown gcoder:gcoder /app/executions

USER gcoder

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]