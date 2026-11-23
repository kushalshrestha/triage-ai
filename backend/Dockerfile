FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# torch is a transitive dep of sentence-transformers (see ADR-0007); the
# default PyPI Linux wheel pulls in several GB of NVIDIA CUDA packages
# that are never used on this CPU-only box, so install the CPU build
# first from PyTorch's own index and let the rest resolve against it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
# spaCy models install as a pip package into site-packages, not lazily
# cached at runtime like the HF models above (hf_cache volume). The
# larger model is a deliberate choice, not Presidio's incidental
# default — see ADR-0032: the smaller en_core_web_sm measured a real
# false positive (a brand name misclassified as a location) that
# en_core_web_lg did not.
RUN python -m spacy download en_core_web_lg

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
