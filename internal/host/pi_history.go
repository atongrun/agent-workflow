package host

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/atongrun/agent-workflow/internal/core"
)

const maxNativeHistoryBytes = 16 * 1024 * 1024
const maxNativeHistoryEntries = 20000

type nativeHistory struct {
	Entries []json.RawMessage `json:"entries"`
	LeafID  *string           `json:"leafId"`
}
type historyResponse struct {
	Messages []json.RawMessage `json:"messages"`
	Session  *core.Session     `json:"session"`
	History  nativeHistory     `json:"history"`
	Source   string            `json:"historySource"`
	Status   string            `json:"historyStatus"`
	Error    string            `json:"historyError,omitempty"`
}

// A history read never calls client(), starts a process or reserves a slot.
func (s *Server) messages(w http.ResponseWriter, r *http.Request) {
	role := r.URL.Query().Get("role")
	if role == "" {
		role = "architect"
	}
	if !validPiRole(role) || len(r.URL.Query()) > 1 || len(r.URL.Query()["role"]) > 1 || (len(r.URL.Query()) == 1 && r.URL.Query()["role"] == nil) {
		writeError(w, fail("invalid_role", "supply one architect or reviewer role", 400))
		return
	}
	id := r.PathValue("id")
	task, err := s.task(id)
	if err != nil {
		writeError(w, err)
		return
	}
	if task.DeletedAt != nil {
		writeError(w, fail("task_deleted", "restore this task before opening its native conversation", 409))
		return
	}
	ref := task.Sessions[role]
	if ref == nil {
		writeError(w, fail("session_unavailable", "native role session does not exist", 409))
		return
	}
	binding := piBinding{role, ref.ID, ref.ProcessID}
	// Only an already-live, exact generation may serve the in-memory branch.
	if _, err := s.boundPiClient(id, binding); err == nil {
		ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
		defer cancel()
		data, readErr := s.piReadCall(ctx, id, binding, "get_messages")
		if readErr != nil {
			writeError(w, readErr)
			return
		}
		var messages struct {
			Messages []json.RawMessage `json:"messages"`
		}
		if json.Unmarshal(data, &messages) != nil {
			writeError(w, fail("native_history_unavailable", "native messages could not be decoded", 503))
			return
		}
		entries, readErr := s.piReadCall(ctx, id, binding, "get_entries")
		if readErr != nil {
			writeError(w, readErr)
			return
		}
		var history nativeHistory
		if json.Unmarshal(entries, &history) != nil || history.Entries == nil {
			writeError(w, fail("native_history_unavailable", "native entries could not be decoded", 503))
			return
		}
		latest, _ := s.task(id)
		if latest == nil || latest.DeletedAt != nil || !bindingMatches(latest.Sessions[role], binding) || !latest.Sessions[role].Available {
			writeError(w, fail("stale_pi_session", "Pi process changed during the history read", 409))
			return
		}
		if messages.Messages == nil {
			messages.Messages = []json.RawMessage{}
		}
		writeJSON(w, 200, historyResponse{messages.Messages, latest.Sessions[role], history, "native", "complete", ""})
		return
	}
	out := s.persistedHistory(task, role)
	writeJSON(w, 200, out)
}

func (s *Server) persistedHistory(task *core.Task, role string) historyResponse {
	ref := task.Sessions[role]
	out := historyResponse{Messages: []json.RawMessage{}, Session: ref, History: nativeHistory{Entries: []json.RawMessage{}}, Source: "none", Status: "complete"}
	unavailable := func(reason string) historyResponse { out.Status = "unavailable"; out.Error = reason; return out }
	directory := filepath.Join(s.cfg.DataDir, "sessions", task.ID, role)
	// Only read the Host-owned native directory; reject links and foreign paths.
	for _, path := range []string{filepath.Join(s.cfg.DataDir, "sessions"), filepath.Join(s.cfg.DataDir, "sessions", task.ID), directory} {
		info, err := os.Lstat(path)
		if os.IsNotExist(err) && !ref.Persisted {
			return out
		}
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return unavailable("Native history directory is unavailable")
		}
	}
	path := ref.File
	if path == "" {
		entries, err := os.ReadDir(directory)
		if err != nil {
			return unavailable("Native history directory is unreadable")
		}
		for _, entry := range entries {
			if strings.HasSuffix(entry.Name(), ".jsonl") {
				if path != "" {
					return unavailable("Native history identity is ambiguous")
				}
				path = filepath.Join(directory, entry.Name())
			}
		}
	}
	if path == "" {
		if ref.Persisted {
			return unavailable("Previously persisted native history is missing")
		}
		return out
	}
	if filepath.Dir(filepath.Clean(path)) != directory {
		return unavailable("Native history is outside the managed session directory")
	}
	info, err := os.Lstat(path)
	if os.IsNotExist(err) && !ref.Persisted {
		return out
	}
	if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 || info.Size() > maxNativeHistoryBytes {
		return unavailable("Native history file is unavailable or exceeds the read limit")
	}
	f, err := os.Open(path)
	if err != nil {
		return unavailable("Native history file is unreadable")
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return unavailable("Native history changed while opening")
	}
	data, err := io.ReadAll(io.LimitReader(f, maxNativeHistoryBytes+1))
	if err != nil || len(data) > maxNativeHistoryBytes {
		return unavailable("Native history could not be read within the size limit")
	}
	return projectNativeHistory(out, data, ref.ID)
}

// Protocol/tree parsing only. It neither migrates files nor rebuilds Pi context.
func projectNativeHistory(out historyResponse, data []byte, sessionID string) historyResponse {
	lines := bytes.Split(data, []byte{'\n'})
	var header struct {
		Type    string `json:"type"`
		Version int    `json:"version"`
		ID      string `json:"id"`
	}
	if len(lines) < 2 || json.Unmarshal(lines[0], &header) != nil || header.Type != "session" || header.ID != sessionID || (header.Version != 2 && header.Version != 3) {
		out.Status = "unavailable"
		out.Error = "Native history header, version or session identity cannot be verified"
		return out
	}
	out.Source = "persisted"
	if len(lines[len(lines)-1]) != 0 {
		out.Status = "incomplete"
		out.Error = "Native history has an unfinished final record"
	}
	parents := map[string]*string{}
	messages := map[string]json.RawMessage{}
	for _, line := range lines[1 : len(lines)-1] {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var entry struct {
			Type    string          `json:"type"`
			ID      string          `json:"id"`
			Parent  json.RawMessage `json:"parentId"`
			Message json.RawMessage `json:"message"`
		}
		var parent *string
		if len(out.History.Entries) >= maxNativeHistoryEntries || json.Unmarshal(line, &entry) != nil || entry.Type == "" || entry.Type == "session" || entry.ID == "" || len(entry.Parent) == 0 || json.Unmarshal(entry.Parent, &parent) != nil {
			out.Status = "incomplete"
			out.Error = "Native history has an invalid record or exceeds the entry limit"
			break
		}
		if _, exists := parents[entry.ID]; exists {
			out.Status = "incomplete"
			out.Error = "Native history contains duplicate entry identities"
			break
		}
		if parent != nil {
			if _, exists := parents[*parent]; !exists {
				out.Status = "incomplete"
				out.Error = "Native history contains an unavailable parent"
				break
			}
		}
		var messageObject map[string]json.RawMessage
		var messageRole string
		if entry.Type == "message" && (json.Unmarshal(entry.Message, &messageObject) != nil || messageObject == nil || json.Unmarshal(messageObject["role"], &messageRole) != nil || messageRole == "") {
			out.Status = "incomplete"
			out.Error = "Native history contains an invalid message"
			break
		}
		parents[entry.ID] = parent
		if entry.Type == "message" {
			messages[entry.ID] = entry.Message
		}
		out.History.Entries = append(out.History.Entries, append(json.RawMessage(nil), line...))
		leaf := entry.ID
		out.History.LeafID = &leaf
	}
	// Pi's file-load leaf is the last valid entry; follow its parent chain only.
	for id := out.History.LeafID; id != nil; id = parents[*id] {
		if message, ok := messages[*id]; ok {
			out.Messages = append(out.Messages, message)
		}
	}
	for i, j := 0, len(out.Messages)-1; i < j; i, j = i+1, j-1 {
		out.Messages[i], out.Messages[j] = out.Messages[j], out.Messages[i]
	}
	return out
}
