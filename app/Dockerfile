FROM python:3.11-slim

# Change workdir to match the mount point
WORKDIR /app

ENV TZ=Asia/Singapore

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Don't copy files - they'll be mounted via volume
# COPY . .

EXPOSE 5000

CMD ["python", "app.py"]