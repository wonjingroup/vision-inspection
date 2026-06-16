FROM python:3.12-slim

# 시스템 패키지 (OpenCV 의존성 + 한글 폰트)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 복사
COPY . .

# 데이터 디렉토리
RUN mkdir -p data models train_work

# 환경변수
ENV DEMO_MODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "main.py", "--port", "8000", "--demo"]
