FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/
COPY experts/ /app/experts/
COPY --from=web /web/dist /app/static
COPY start.sh /start.sh
RUN chmod +x /start.sh
ENV STATIC_DIR=/app/static
ENV EXPERTS_DIR=/app/experts
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["/start.sh"]
