FROM docker:27-cli AS docker-cli
FROM python:3.12-slim
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /srv
RUN useradd --uid 10001 --create-home capsule
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt
COPY worker_runtime.py .
COPY browser_task.py .
COPY capsule_runtime.py .
USER 10001
ENV HOME=/home/capsule PYTHONDONTWRITEBYTECODE=1
EXPOSE 8081
CMD ["uvicorn","worker_runtime:app","--host","0.0.0.0","--port","8081"]
