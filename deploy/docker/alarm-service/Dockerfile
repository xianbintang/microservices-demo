FROM python:3.11-slim

WORKDIR /app

# 先安装依赖（利用 Docker 缓存层，依赖不变时不重复安装）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/server.py
COPY feishu_api.py /app/feishu_api.py
COPY problem_manager.py /app/problem_manager.py
COPY init_mock_data.py /app/init_mock_data.py
COPY static/ /app/static/

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 9095

CMD ["python", "server.py"]
