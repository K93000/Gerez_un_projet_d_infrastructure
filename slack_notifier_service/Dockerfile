FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir --disable-pip-version-check \
    kafka-python-ng==2.2.3 \
    psycopg2-binary==2.9.9 \
    requests==2.32.3

COPY config.py slack_notifier.py ./

CMD ["python", "slack_notifier.py"]