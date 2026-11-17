# Backend dev image. Linux containers avoid Windows Smart App Control DLL blocks (DEC-20).
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# libgomp1: OpenMP runtime required by LightGBM; make: Makefile targets run inside the container (DEC-31)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 make && rm -rf /var/lib/apt/lists/*
WORKDIR /repo/backend
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install --no-cache-dir -e ".[dev]"
# DEC-85: EMBED=1 adds multilingual-e5-small support (CPU torch, about 1 GB). Default 0: fallback embedder.
ARG EMBED=0
RUN if [ "$EMBED" = "1" ]; then \
      pip install --no-cache-dir "torch==2.15.0+cpu" --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir -e ".[dev,embed]"; fi
COPY . .
EXPOSE 8000
CMD ["sh", "/repo/backend/docker/start.sh"]
