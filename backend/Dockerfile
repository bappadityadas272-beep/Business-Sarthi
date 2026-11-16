# Backend dev image. Linux containers avoid Windows Smart App Control DLL blocks (DEC-20).
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# libgomp1: OpenMP runtime required by LightGBM; make: Makefile targets run inside the container (DEC-31)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 make && rm -rf /var/lib/apt/lists/*
WORKDIR /repo/backend
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install --no-cache-dir -e ".[dev]"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
