#!/bin/bash


cd /home/gcoder/bgutil-ytdlp-pot-provider/server/
node build/main.js &

cd /app
uvicorn app:app --host 0.0.0.0 --port 8000