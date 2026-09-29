# OpsPilot agent API. Every investigation spawns the MCP tool server as a subprocess, so the image
# carries the agent, the API and the MCP server. The live telemetry backend reads container logs
# with the Docker CLI, copied from the official docker image.
# Build from the repository root: docker build -f api/Dockerfile .
FROM docker:29-cli AS docker-cli

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY pyproject.toml README.md LICENSE ./
COPY agent ./agent
COPY api ./api
COPY mcp-servers ./mcp-servers
COPY evals ./evals
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data /app/evals/results \
    && chown app /data

ENV OPSPILOT_API_HOST=0.0.0.0 \
    OPSPILOT_API_PORT=8080 \
    OPSPILOT_API_DATA_DIR=/data \
    OPSPILOT_RESULTS_DIR=/app/evals/results

USER app
EXPOSE 8080
VOLUME ["/data"]
CMD ["opspilot-api"]
