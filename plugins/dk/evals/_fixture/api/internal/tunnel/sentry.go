// Package tunnel forwards browser error reports to Sentry, so ad blockers do not drop them.
package tunnel

import (
	"io"
	"net/http"
)

const ingest = "https://o0.ingest.sentry.io/api/0/envelope/"

// Handler relays the request body to Sentry's ingest endpoint with client.
func Handler(client *http.Client) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp, err := client.Post(ingest, "application/x-sentry-envelope", io.LimitReader(r.Body, 1<<20))
		if err != nil {
			http.Error(w, "upstream unavailable", http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()
		w.WriteHeader(resp.StatusCode)
	})
}
