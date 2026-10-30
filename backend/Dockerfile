# syntax=docker/dockerfile:1
FROM python:3.12-slim

# RDKit's drawing code and Pillow need these at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libxrender1 libxext6 libexpat1 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app/backend
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# config.py resolves DATA and the .env file from the repo root, two levels up,
# so the layout inside the image mirrors the repo.
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "orchanium.api:app", "--host", "0.0.0.0", "--port", "8000"]
