package host

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"path"
	"strings"
	"unicode/utf8"

	"github.com/atongrun/agent-workflow/internal/core"
)

// The operator supplies only an endpoint, not new repository credentials. The
// existing Host bearer authorizes the narrow Worker route; any existing Access
// service credential may be reused. Missing/denied access fails closed.
func (s *Server) repositoryBridgeRead(ctx context.Context, t *core.Task, operation, name string, cursor int) (map[string]any, error) {
	endpoint := os.Getenv("AWF_REPOSITORY_READ_URL")
	u, err := url.Parse(endpoint)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "/api/awf/repository-read" || (u.Scheme != "https" && !(u.Scheme == "http" && (u.Hostname() == "127.0.0.1" || u.Hostname() == "localhost" || u.Hostname() == "::1"))) {
		return nil, fail("repository_reader_unavailable", "configure an authorized fixed-source Worker reader before planning beyond the initial bundle", 409)
	}
	if operation != "read" && operation != "list" || cursor < 0 || cursor > 100000 || len(name) > 512 || strings.ContainsAny(name, "\\\x00") {
		return nil, fail("invalid_repository_read", "invalid bounded source read", 400)
	}
	body, _ := json.Marshal(map[string]any{"taskId": t.ID, "targetRevision": t.TargetRevision, "lifecycleRevision": t.LifecycleRevision, "operation": operation, "path": name, "cursor": cursor})
	req, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, fail("repository_reader_unavailable", "repository reader is unavailable", 409)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+s.token)
	if id := os.Getenv("AWF_ACCESS_CLIENT_ID"); id != "" {
		req.Header.Set("CF-Access-Client-Id", id)
		req.Header.Set("CF-Access-Client-Secret", os.Getenv("AWF_ACCESS_CLIENT_SECRET"))
	}
	response, err := s.http.Do(req)
	if err != nil {
		return nil, fail("repository_reader_unavailable", "authorized repository reader did not respond; do not infer missing files", 409)
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, 128*1024+1))
	if err != nil || len(data) > 128*1024 {
		return nil, fail("repository_reader_unavailable", "repository reader response exceeds its verification limit", 409)
	}
	if response.StatusCode != 200 {
		return nil, fail("repository_read_failed", "fixed-source reader denied or could not verify this read; missing code remains unknown", 409)
	}
	var result map[string]any
	if json.Unmarshal(data, &result) != nil || result["repositoryId"] != t.RepositoryID || result["repository"] != t.Repository || result["baseSha"] != t.RepositorySource.BaseSHA || result["targetRevision"] != float64(t.TargetRevision) || result["operation"] != operation || result["path"] != name {
		return nil, fail("repository_reader_mismatch", "repository reader returned a different identity, baseline or path", 409)
	}
	if err := validateBridgeResult(result, operation, name, cursor); err != nil {
		return nil, err
	}
	current, e := s.task(t.ID)
	if e != nil || current.TargetRevision != t.TargetRevision || current.LifecycleRevision != t.LifecycleRevision || current.DeletedAt != nil {
		return nil, fail("target_changed", "repository target changed during source read", 409)
	}
	result["untrustedSource"] = true
	return result, nil
}

func validateBridgeResult(result map[string]any, operation, name string, cursor int) error {
	invalid := func() error {
		return fail("repository_reader_mismatch", "repository reader returned an invalid bounded result; missing source remains unknown", 409)
	}
	if _, ok := result["truncated"].(bool); !ok {
		return invalid()
	}
	next, present := result["nextCursor"]
	if !present {
		return invalid()
	}
	if next != nil {
		n, ok := next.(float64)
		if !ok || math.Trunc(n) != n || n <= float64(cursor) || n > 100000 {
			return invalid()
		}
	}
	if operation == "read" {
		content, ok := result["content"].(string)
		if !ok || len(content) > 65536 || !utf8.ValidString(content) || strings.Contains(content, "\x00") || result["startLine"] != float64(cursor+1) {
			return invalid()
		}
		return nil
	}
	entries, ok := result["entries"].([]any)
	if !ok || len(entries) > 200 {
		return invalid()
	}
	for _, raw := range entries {
		entry, ok := raw.(map[string]any)
		if !ok {
			return invalid()
		}
		file, ok := entry["path"].(string)
		if !ok || file == "" || len(file) > 512 || path.Clean(file) != file || strings.HasPrefix(file, "/") || strings.HasPrefix(file, "../") || file == ".." || strings.ContainsAny(file, "\\\x00") || (name != "" && file != name && !strings.HasPrefix(file, name+"/")) {
			return invalid()
		}
		kind, ok := entry["type"].(string)
		if !ok || (kind != "blob" && kind != "tree" && kind != "commit") {
			return invalid()
		}
		if size, exists := entry["size"]; exists {
			n, ok := size.(float64)
			if !ok || math.Trunc(n) != n || n < 0 {
				return invalid()
			}
		}
	}
	return nil
}
