FROM python:3.12-slim
WORKDIR /app
RUN useradd --uid 10001 --create-home capsula
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py autonomy.py autonomy_daemon.py challenge.py vision.py platform_core.py audit.py artifacts.py federation.py inference.py nexus_bridge.py proof.py policy.py workspaces.py verify_evidence.py verify_governance.py ./
COPY static ./static
RUN mkdir -p /app/data && chown -R capsula:capsula /app/data
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080"]
