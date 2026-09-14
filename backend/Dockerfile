FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# torch is a transitive dep of sentence-transformers (see ADR-0007); the
# default PyPI Linux wheel pulls in several GB of NVIDIA CUDA packages
# that are never used on this CPU-only box, so install the CPU build
# first from PyTorch's own index and let the rest resolve against it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
