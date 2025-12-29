FROM python:3.13-slim

WORKDIR /app

COPY scripts/ ./scripts/

# 默认使用 SQLite 文件：/app/data/dramaradar.db（建议通过 volume 挂载 /app/data 持久化）
ENV DRAMARADAR_DB_PATH=/app/data/dramaradar.db

CMD ["python", "scripts/maoyan_web_heat_monitor.py"]

