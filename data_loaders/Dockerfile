FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

ENV PORT=8080
ENV DATABASE_URL=postgresql://postgres:postgres@postgres:5432/weather

CMD ["python", "main.py"]
