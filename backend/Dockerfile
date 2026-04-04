FROM python:3.11-slim

WORKDIR /app

ARG BACKEND_REQUIREMENTS_FILE=requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb1 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libglib2.0-0 \
    libsm6 \
    libice6 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
COPY backend/requirements-docling.txt /app/requirements-docling.txt

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r "/app/${BACKEND_REQUIREMENTS_FILE}"

COPY backend/app /app/app
COPY backend/tools /app/tools
COPY Spec /app/Spec

COPY data /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
