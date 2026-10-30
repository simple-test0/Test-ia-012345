FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

# System deps occasionally needed by Pillow/torch runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU wheels by default (small image). For NVIDIA GPUs build with:
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --upgrade pip \
    && if echo "$TORCH_INDEX" | grep -q "/cpu"; then \
         sed -i -e '/^xformers/d' \
                -e 's/^onnxruntime-gpu==\([^;]*\);.*/onnxruntime==\1/' \
                -e '/^onnxruntime==.*darwin/d' requirements.txt; \
       fi \
    && pip install -r requirements.txt --extra-index-url "$TORCH_INDEX"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
