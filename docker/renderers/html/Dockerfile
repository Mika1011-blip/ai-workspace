# The html renderer: plays a self-contained HTML canvas animation in headless
# Chromium frame by frame and records it, sound included, into
# /project/artifacts/final-candidate.mp4. Workers never run this; the API does.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.49.1 \
    && playwright install --with-deps chromium

COPY render.py /usr/local/bin/render.py
WORKDIR /project
ENTRYPOINT ["python", "/usr/local/bin/render.py"]
