FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY siu2fhir_au/ siu2fhir_au/
COPY tools/ tools/
COPY samples/ samples/
COPY config/ config/
COPY seed/ seed/
ENV PYTHONUNBUFFERED=1
EXPOSE 2575 8090
CMD ["python", "-m", "siu2fhir_au"]
