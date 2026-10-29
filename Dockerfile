FROM python:3.12-slim

WORKDIR /app

# ffmpeg: frame extraction for climbing videos; git + ssh: pull the climbing repo
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompts ./prompts

RUN mkdir -p /app/data && useradd -m appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
