# EDGAR.AI as one container: the React app is built, then served by the FastAPI backend.
# Used by Hugging Face Spaces (Docker SDK), which expects the app on port 7860.

# ---- 1. build the React front end
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Python backend serving the built app
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Spaces run the container as user 1000
RUN useradd -m -u 1000 user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user *.py ./
COPY --chown=user --from=web /web/dist frontend/dist

USER user
# DuckDB's full-text search extension, installed at build time for the 10-K passage search
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL fts')"

EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
