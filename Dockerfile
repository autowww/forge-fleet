FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*
COPY fleet_server /app/fleet_server
ENV PYTHONPATH=/app
EXPOSE 18765
CMD ["python3", "-m", "fleet_server", "--host", "0.0.0.0", "--port", "18765"]
