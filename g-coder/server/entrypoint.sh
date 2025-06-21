#!/bin/bash


cd /home/gcoder/bgutil-ytdlp-pot-provider/server/
node build/main.js &

cd /home/gcoder/executions
uvicorn --app-dir /app app:app --host 0.0.0.0 --port 8000