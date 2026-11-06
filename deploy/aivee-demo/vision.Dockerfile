# Cloud vision worker for the server: the edge image (apps/edge/Dockerfile) with the models
# baked in, since a swarm task has no repo checkout to mount them from. build.sh builds the
# edge image first and passes it as BASE; `models` is a named build context (the models dir).
# COPY of a directory copies its contents, hence one line per model dir.
ARG BASE
FROM ${BASE}
COPY --from=models --chown=10001 yolo11n_int8_openvino_model /app/models/yolo11n_int8_openvino_model
COPY --from=models --chown=10001 yolo11n-pose_int8_openvino_model /app/models/yolo11n-pose_int8_openvino_model
COPY --from=models --chown=10001 face_detection_yunet_2023mar.onnx /app/models/face_detection_yunet_2023mar.onnx
