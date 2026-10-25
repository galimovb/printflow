# Образ printflow: все товары (шопперы, коврики) в одном приложении + три модуля ядра футболок
# без побочных эффектов (правила промптов и хромакей — для принта шоппера).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SM_HOST=0.0.0.0 SM_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends fonts-montserrat fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY printflow/requirements.txt printflow/
RUN pip install --no-cache-dir -r printflow/requirements.txt

COPY server/__init__.py server/prompts.py server/print_generation.py server/print_raster.py server/
RUN python -m playwright install --with-deps chromium
COPY printflow printflow

EXPOSE 8090
CMD ["python", "-m", "printflow"]
