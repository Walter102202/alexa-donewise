FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "aws-opentelemetry-distro>=0.18.0,<1.0.0"
COPY client.py ./client.py
COPY agentcore/app.py ./main.py
EXPOSE 8080
CMD ["opentelemetry-instrument", "python", "main.py"]
