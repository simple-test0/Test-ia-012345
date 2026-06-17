FROM python:3.11-slim

WORKDIR /app

# System deps occasionally needed by Pillow/torch runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# For GPU builds, swap the index URL for the cu121 wheels (see README).
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
       --extra-index-url https://download.pytorch.org/whl/cpu

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
