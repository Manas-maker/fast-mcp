FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir .

ENTRYPOINT ["fast-mcp", "stdio", "fast_mcp.demo:app"]
