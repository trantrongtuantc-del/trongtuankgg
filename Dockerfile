FROM python:3.11-slim

# Thư mục làm việc trong container
WORKDIR /app

# Copy requirements trước (tận dụng Docker cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ source code
COPY . .

# Chạy bot
CMD ["python", "main.py"]
