FROM mcr.microsoft.com/devcontainers/python:3.10

# Install runtime dependencies needed by this project
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip \
    && pip install poetry \
    && poetry config virtualenvs.create false
