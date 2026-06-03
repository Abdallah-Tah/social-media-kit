# Social Media Agent — container image.
# Build:  docker build -t social-media-agent .
# Run:    docker run --rm --env-file config/secrets.env social-media-agent \
#             run --topic "Your topic" --dry-run
FROM python:3.12-slim

# System fonts so Pillow can render cards/cover fallbacks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY agent ./agent
COPY scripts ./scripts
COPY config ./config
COPY skills ./skills
COPY README.md ./

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir .

# The web dashboard listens here (run: docker run -p 8800:8800 ... dashboard --host 0.0.0.0).
EXPOSE 8800

# `smkit` is the entrypoint; pass subcommands as args.
ENTRYPOINT ["smkit"]
CMD ["--help"]
