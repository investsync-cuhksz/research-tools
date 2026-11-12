# InvestSync Research Tools: API server image (Tencent Cloud Lighthouse, Hong Kong)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Fonts for the tear sheet: Inter (Latin) + Noto CJK (Chinese names). Chromium prints the SEC's web-page filings to
# PDF for the student source pack (investsync/render/html_pdf.py; without it the pack keeps the web pages).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-inter fonts-noto-cjk chromium \
 && rm -rf /var/lib/apt/lists/*
ENV CHROME_PATH=/usr/bin/chromium

WORKDIR /app
# On mainland networks, build with:  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY investsync ./investsync
COPY api ./api
COPY config ./config
COPY generate.py .

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
