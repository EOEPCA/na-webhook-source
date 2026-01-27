FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY main.py .
COPY function ./function

ENV PORT=8080
EXPOSE 8080

CMD ["python", "main.py"]
