FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PRIVATESMS_DEFAULT_MODEL_PATH=/app/models/rbt3-six-class \
    PIP_CONSTRAINT=/app/constraints/api.txt

WORKDIR /app
COPY constraints/api.txt ./constraints/api.txt
COPY requirements/api.txt ./requirements/api.txt
RUN python -m pip install --no-cache-dir -c constraints/api.txt -r requirements/api.txt
ARG INSTALL_TRANSFORMER=0
ARG INSTALL_ONNX=1
RUN if [ "$INSTALL_TRANSFORMER" = "1" ]; then \
      python -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    fi \
    && if [ "$INSTALL_TRANSFORMER" = "1" ]; then \
      python -m pip install --no-cache-dir -c constraints/api.txt 'transformers>=4.45,<6'; \
    fi \
    && if [ "$INSTALL_ONNX" = "1" ]; then \
      python -m pip install --no-cache-dir -c constraints/api.txt 'onnx>=1.16,<2' 'onnxruntime>=1.19,<2' 'transformers>=4.45,<6'; \
    fi
COPY pyproject.toml README.md ./
COPY src ./src
COPY models ./models
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation . \
    && useradd --create-home --uid 10001 appuser

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "privatesms.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
