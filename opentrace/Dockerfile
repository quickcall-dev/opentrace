FROM python:3.12-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/* \
    && git config --global --add safe.directory '*'

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml README.md ./
COPY opentrace/ opentrace/

RUN uv pip install --system --no-cache -e .

EXPOSE 19777

CMD ["python", "-m", "opentrace.server"]
