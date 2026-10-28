# 多阶段构建：编译期用 golang，运行期用极简镜像
FROM golang:1.21 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /imserver ./cmd/server

FROM debian:bookworm-slim
WORKDIR /app
COPY --from=build /imserver /app/imserver
COPY web ./web
EXPOSE 8080
CMD ["/app/imserver"]
