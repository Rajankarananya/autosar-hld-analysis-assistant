FROM python:3.11-slim

# Install system dependency for OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend.py app.py ./

RUN mkdir -p uploads data

EXPOSE 8000 8501

# Run both backend and frontend
CMD uvicorn backend:app --host 0.0.0.0 --port 8000 & \
    streamlit run app.py --server.port 8501 --server.address 0.0.0.0