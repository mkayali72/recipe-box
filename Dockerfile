# -----------------------------------------------------------------------------
# Recipe Box application image.
# This image contains only the Python web service. PostgreSQL runs separately
# in Docker Compose so the two processes remain independently maintainable.
# -----------------------------------------------------------------------------

# Use the requested slim Python image to keep the application footprint small.
FROM python:3.12-slim

# Avoid .pyc files and buffered logs, and prevent pip from retaining a cache
# layer that would make the final image larger than necessary.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Keep all application files under one predictable directory in the image.
WORKDIR /app

# Install dependencies before copying source code so Docker can reuse this
# layer when only application code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the application package; .dockerignore removes local-only files
# such as .env, virtual environments, Git metadata, and Python caches.
COPY app ./app

# Document the port used by the single Uvicorn process.
EXPOSE 8000

# Run one worker because Recipe Box is a single-user app designed for low
# memory usage. Docker Compose supplies the environment configuration.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]