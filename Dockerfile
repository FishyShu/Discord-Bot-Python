FROM python:3.12-slim

LABEL version="1.3.0" \
      description="Discord Bot — music, moderation, AI chatbot, and more"

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd -r botuser && useradd -r -g botuser -d /app botuser && \
    mkdir -p /app/data/uploads && chown -R botuser:botuser /app/data

EXPOSE 5000

USER botuser

CMD ["python", "bot.py"]
