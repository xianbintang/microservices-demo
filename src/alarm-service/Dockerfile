FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir lark-oapi

COPY server.py /app/server.py
COPY feishu_api.py /app/feishu_api.py
COPY .env /app/.env

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 9095

CMD ["python", "server.py"]
