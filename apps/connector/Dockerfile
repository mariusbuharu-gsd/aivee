# AiVee stream connector for the restaurant side of cloud mode. Build from the repo root:
#   docker build -f apps/connector/Dockerfile -t aivee-connector .
# Run on any PC or small box in the restaurant network:
#   docker run -d --restart unless-stopped -e SOURCE=rtsp://CAMERA/stream -e CAMERA_ID=cam-01 \
#     -e CLOUD_RTSP_URL=rtsp://CLOUD:8554 -e STREAM_PUBLISH_USER=... -e STREAM_PUBLISH_PASSWORD=... \
#     aivee-connector
FROM alpine:3.20
RUN apk add --no-cache python3 ffmpeg
COPY apps/connector/connector.py /app/connector.py
USER nobody
ENTRYPOINT ["python3", "/app/connector.py"]
