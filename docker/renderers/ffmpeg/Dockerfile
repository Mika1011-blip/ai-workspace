FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core librsvg2-bin \
    && rm -rf /var/lib/apt/lists/*

COPY render.py /usr/local/bin/render.py
WORKDIR /project
ENTRYPOINT ["python", "/usr/local/bin/render.py"]
