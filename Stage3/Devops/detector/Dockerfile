FROM python:3.11-slim

WORKDIR /app

# Install iptables so the detector can add/remove firewall rules.
# Also install procps for system monitoring utilities.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iptables procps \
    && rm -rf /var/lib/apt/lists/*

# Create the directories where we write audit and detector logs
RUN mkdir -p /var/log/detector

# Copy and install Python dependencies first (Docker caches this layer
# separately from the source code, so rebuilds are faster if only code changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the detector source code
COPY . .

# Run the main daemon
CMD ["python", "main.py"]
