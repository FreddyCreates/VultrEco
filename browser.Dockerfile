FROM mcr.microsoft.com/playwright/python:v1.57.0-noble
WORKDIR /srv
RUN useradd --uid 10001 --create-home capsule
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt
COPY worker_runtime.py .
RUN mkdir -p /home/capsule && chown -R 10001:10001 /srv /home/capsule
USER 10001
ENV HOME=/home/capsule PYTHONDONTWRITEBYTECODE=1
EXPOSE 8081
CMD ["uvicorn","worker_runtime:app","--host","0.0.0.0","--port","8081"]
