FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY main.py .
COPY function ./function

RUN pip install --no-cache-dir .

ENV PORT=8080
EXPOSE 8080

CMD ["python", "main.py"]
