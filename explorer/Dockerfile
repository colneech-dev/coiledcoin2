FROM python:3.12-slim
WORKDIR /app
COPY explorer.py .
# The address index lives in /data; mount a volume there.
ENV CLC2_EXPLORER_DB=/data/explorer.db
RUN mkdir /data && chown nobody /data
VOLUME /data
EXPOSE 8080
# Set CLC2_RPC_USER / CLC2_RPC_PASSWORD and pass --rpc-url to reach the node (see README).
USER nobody
ENTRYPOINT ["python", "-I", "explorer.py", "--host", "0.0.0.0"]
