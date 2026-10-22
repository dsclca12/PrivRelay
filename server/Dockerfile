FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /privrelay .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates && addgroup -g 10001 relay && adduser -D -u 10001 -G relay relay && mkdir /data && chown relay:relay /data
USER relay
WORKDIR /app
COPY --from=build /privrelay /app/privrelay
EXPOSE 8787
HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=12 \
  CMD wget -q -T 3 -O /dev/null http://127.0.0.1:8787/healthz || exit 1
ENTRYPOINT ["/app/privrelay"]
CMD ["-listen", "0.0.0.0:8787", "-data", "/data/privrelay.enc"]
