# Build on an isolated worker VM. Run each browser task as a disposable container.
FROM mcr.microsoft.com/playwright/python:v1.57.0-noble
RUN useradd --uid 10001 --create-home capsula && mkdir -p /app && chown 10001:10001 /app
WORKDIR /app
COPY src/capsula/execution/browser_task.py /app/browser_task.py
USER 10001
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "/app/browser_task.py"]
