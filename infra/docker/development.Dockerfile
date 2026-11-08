FROM python:3.12-slim
WORKDIR /app
RUN useradd --uid 10001 --create-home capsula
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY apps/web/static ./apps/web/static
COPY runtimes/dot/dot ./runtimes/dot/dot
RUN mkdir -p /app/data && chown -R capsula:capsula /app/data
USER 10001
ENV PYTHONPATH=/app/src:/app PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["uvicorn","capsula.api.app:app","--host","0.0.0.0","--port","8080"]
