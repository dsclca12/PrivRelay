FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
WORKDIR /app
COPY requirements/classifier-runtime.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt
COPY integrations/PrivateSMS-Classifier /app/upstream
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation /app/upstream \
    && useradd --create-home --uid 10001 classifier \
    && mkdir /app/feedback && chown classifier:classifier /app/feedback
ENV PRIVATESMS_MODEL_PATH=/app/upstream/models/rbt3-six-class \
    PRIVATESMS_FEEDBACK_DB=/app/feedback/feedback.sqlite3 \
    PRIVATESMS_INFERENCE_THREADS=4
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "privatesms.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
