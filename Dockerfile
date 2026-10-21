FROM node:22-alpine AS web
WORKDIR /web
COPY web_client/package*.json ./
RUN npm ci
COPY web_client/ ./
RUN npm run build

FROM golang:1.25-alpine AS build
WORKDIR /src
COPY server/go.mod server/go.sum ./
RUN go mod download
COPY server/*.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /privrelay .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates && addgroup -g 10001 relay && adduser -D -u 10001 -G relay relay && mkdir /data && chown relay:relay /data
USER relay
WORKDIR /app
COPY --from=build /privrelay /app/privrelay
COPY --from=web /web/dist /app/web
EXPOSE 8787
ENTRYPOINT ["/app/privrelay"]
CMD ["-listen", "0.0.0.0:8787", "-data", "/data/privrelay.enc", "-web", "/app/web"]
