FROM python:3.11-slim

# Install system build dependencies for ortools, scipy, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
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
    && pip cache purge

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Set workspace directory
WORKDIR /workspace
VOLUME ["/workspace"]

# Switch to non-root user
USER appuser

CMD ["python"]
