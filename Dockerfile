FROM python:3.13-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "main.py"]

RUN apt-get install -y libopus0
RUN apt-get update && apt-get install -y ffmpeg
RUN pip install yt-dlp

pip install spotipy
ffmpeg -version
yt-dlp --version
