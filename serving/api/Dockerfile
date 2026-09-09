# Imagen de serving: NO reproduce el entorno de entrenamiento.
#
# El contenedor lleva onnxruntime, numpy y fastapi. No lleva LightGBM, pandas,
# scikit-learn ni PyTorch, que juntos pesan cientos de megabytes y arrastran su
# propia cadena de versiones. Esa separacion es la razon de exportar a ONNX.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CRMLOPS_ARTIFACTS=/app/artifacts

WORKDIR /app

# Dependencias primero: la capa se cachea mientras no cambien.
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "onnxruntime>=1.19" \
        "numpy>=1.26"

# El modelo y su contrato. Ninguno sirve sin el otro.
COPY exports/onnx/model.onnx     /app/artifacts/model.onnx
COPY exports/onnx/contract.json  /app/artifacts/contract.json
COPY serving/api/app.py          /app/app.py
COPY serving/api/onnx_runtime.py /app/onnx_runtime.py

# Usuario sin privilegios: un servicio de scoring no necesita root.
RUN useradd --create-home --uid 10001 scoring && chown -R scoring /app
USER scoring

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
