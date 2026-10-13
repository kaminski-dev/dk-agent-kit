FROM golang:1.27.1-alpine AS build
WORKDIR /src
COPY go.* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /api ./cmd/api

FROM gcr.io/distroless/static
COPY --from=build /api /api
ENTRYPOINT ["/api"]
