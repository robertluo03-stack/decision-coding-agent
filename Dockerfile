FROM python:3.11-slim

# Layer 1: update package index (cached independently)
RUN apt-get update

# Layer 2: install system build dependencies
RUN apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (pyproject.toml + data science packages)
RUN pip install --no-cache-dir \
    langgraph>=0.2.0 \
    langchain-deepseek>=1.0.0 \
    mcp>=1.0.0 \
    python-dotenv>=1.0.0 \
    loguru>=0.7.0 \
    rich>=13.0.0 \
    pandas \
    numpy \
    scipy \
    ortools \
    plotly>=5.0 \
    duckdb>=0.10 \
    openpyxl>=3.0 \
    && pip cache purge

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Set workspace directory
WORKDIR /workspace
VOLUME ["/workspace"]

# Switch to non-root user
USER appuser

CMD ["python"]
