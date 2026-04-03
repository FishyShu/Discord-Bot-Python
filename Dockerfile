FROM python:3.12-slim

LABEL version="1.9.3" \
      description="Discord Bot — music, moderation, AI chatbot, and more"

# Upgrade base packages first to patch known debian CVEs, then install deps.
# build-essential is removed after pip install — only needed for compilation.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends ffmpeg build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y --auto-remove build-essential

COPY . .

RUN groupadd -r botuser && useradd -r -g botuser -d /app botuser && \
    mkdir -p /app/data/uploads && chown -R botuser:botuser /app/data

EXPOSE 5000

USER botuser

CMD ["python", "bot.py"]
