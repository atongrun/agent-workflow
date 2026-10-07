package content

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

type Credential struct {
	Token string `json:"token"`
	Owner string `json:"owner"`
}

func (s *Service) Handler(credentials []Credential) (http.Handler, error) {
	if len(credentials) == 0 || len(credentials) > 256 {
		return nil, ErrInvalid
	}
	type credential struct {
		hash  [32]byte
		owner string
	}
	keys := make([]credential, 0, len(credentials))
	seen := map[[32]byte]bool{}
	for _, c := range credentials {
		h := sha256.Sum256([]byte(c.Token))
		if len(c.Token) < 24 || c.Owner == "" || len(c.Owner) > 128 || seen[h] {
			return nil, ErrInvalid
		}
		seen[h] = true
		keys = append(keys, credential{h, c.Owner})
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		if len(r.Header.Values("Authorization")) != 1 || !strings.HasPrefix(header, "Bearer ") || len(header) > 4096 {
			writeCode(w, 401, "unauthorized")
			return
		}
		h := sha256.Sum256([]byte(strings.TrimPrefix(header, "Bearer ")))
		owner := ""
		for _, c := range keys {
			if subtle.ConstantTimeCompare(h[:], c.hash[:]) == 1 {
				owner = c.owner
			}
		}
		if owner == "" {
			writeCode(w, 401, "unauthorized")
			return
		}
		s.serve(w, r, owner)
	}), nil
}

func (s *Service) serve(w http.ResponseWriter, r *http.Request, owner string) {
	path := strings.TrimPrefix(r.URL.Path, "/v1/content/jobs")
	if !strings.HasPrefix(r.URL.Path, "/v1/content/jobs") {
		writeCode(w, 404, "not_found")
		return
	}
	if path == "" {
		switch r.Method {
		case http.MethodPost:
			if r.URL.RawQuery != "" {
				writeCode(w, 400, "invalid_request")
				return
			}
			r.Body = http.MaxBytesReader(w, r.Body, MaxBodyBytes)
			b, err := io.ReadAll(r.Body)
			if err != nil {
				var size *http.MaxBytesError
				if errors.As(err, &size) {
					writeCode(w, 413, "body_too_large")
				} else {
					writeCode(w, 400, "invalid_request")
				}
				return
			}
			in, hash, err := ParseInput(b)
			if err != nil {
				writeCode(w, 400, "invalid_request")
				return
			}
			j, err := s.Enqueue(r.Context(), owner, in, hash)
			if err != nil {
				writeLedgerError(w, err)
				return
			}
			writeJSON(w, 202, j)
		case http.MethodGet:
			q, queryErr := url.ParseQuery(r.URL.RawQuery)
			if queryErr != nil {
				writeCode(w, 400, "invalid_request")
				return
			}
			for k, values := range q {
				if (k != "limit" && k != "before") || len(values) != 1 {
					writeCode(w, 400, "invalid_request")
					return
				}
			}
			limit := 20
			if q.Has("limit") {
				n, err := strconv.Atoi(q.Get("limit"))
				if err != nil || n < 1 || n > 100 {
					writeCode(w, 400, "invalid_request")
					return
				}
				limit = n
			}
			before := q.Get("before")
			if q.Has("before") && !validID(before) {
				writeCode(w, 400, "invalid_request")
				return
			}
			p, err := s.ledger.List(r.Context(), owner, before, limit)
			if err != nil {
				writeLedgerError(w, err)
				return
			}
			writeJSON(w, 200, p)
		default:
			writeCode(w, 405, "method_not_allowed")
		}
		return
	}
	parts := strings.Split(strings.TrimPrefix(path, "/"), "/")
	if !strings.HasPrefix(path, "/") || len(parts) > 2 || !validID(parts[0]) || r.URL.RawQuery != "" {
		writeCode(w, 404, "not_found")
		return
	}
	if len(parts) == 1 && r.Method == http.MethodGet {
		j, err := s.ledger.Get(r.Context(), owner, parts[0])
		if err != nil {
			writeLedgerError(w, err)
			return
		}
		writeJSON(w, 200, j)
		return
	}
	if len(parts) == 2 && parts[1] == "cancel" && r.Method == http.MethodPost {
		// Cancellation takes no body, so it cannot smuggle another owner or input.
		b, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1))
		if err != nil || len(b) != 0 {
			writeCode(w, 400, "invalid_request")
			return
		}
		j, err := s.Cancel(r.Context(), owner, parts[0])
		if err != nil {
			writeLedgerError(w, err)
			return
		}
		writeJSON(w, 200, j)
		return
	}
	writeCode(w, 404, "not_found")
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeCode(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code}})
}

func writeLedgerError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrNotFound):
		writeCode(w, 404, "not_found")
	case errors.Is(err, ErrConflict):
		writeCode(w, 409, "request_conflict")
	case errors.Is(err, ErrQueueFull):
		writeCode(w, 429, "queue_full")
	case errors.Is(err, ErrInvalid):
		writeCode(w, 400, "invalid_request")
	default:
		writeCode(w, 503, "unavailable")
	}
}
