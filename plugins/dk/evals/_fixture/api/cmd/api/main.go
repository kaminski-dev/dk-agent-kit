// Command api serves the booking API over HTTP/2 cleartext behind the load balancer.
package main

import (
	"log"
	"net/http"

	"golang.org/x/net/http2"
	"golang.org/x/net/http2/h2c"

	"example.com/api/internal/tunnel"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok")) })
	mux.Handle("POST /tunnel", tunnel.Handler(http.DefaultClient))
	log.Fatal(http.ListenAndServe(":8080", h2c.NewHandler(mux, &http2.Server{})))
}
