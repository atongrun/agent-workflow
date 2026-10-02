package core

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type Store struct {
	mu    sync.Mutex
	path  string
	state State
	lock  *os.File
	fault error
}

func ID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(err)
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	s := hex.EncodeToString(b[:])
	return s[:8] + "-" + s[8:12] + "-" + s[12:16] + "-" + s[16:20] + "-" + s[20:]
}
func Open(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	s := &Store{path: filepath.Join(dir, "state.json"), state: State{Version: 1, Settings: Defaults(), Tasks: map[string]*Task{}, Requests: map[string]*Request{}, Events: []Event{}}}
	lock, err := lockState(filepath.Join(dir, "host.lock"))
	if err != nil {
		return nil, err
	}
	s.lock = lock
	success := false
	defer func() {
		if !success {
			_ = lock.Close()
		}
	}()
	data, err := os.ReadFile(s.path)
	if errors.Is(err, os.ErrNotExist) {
		if err = s.persist(); err != nil {
			return nil, err
		}
		success = true
		return s, nil
	}
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(data, &s.state); err != nil {
		return nil, fmt.Errorf("read state: %w", err)
	}
	if s.state.Version != 1 || s.state.Tasks == nil || s.state.Requests == nil {
		return nil, errors.New("unsupported or invalid state")
	}
	success = true
	return s, nil
}
func (s *Store) persist() error {
	b, err := json.MarshalIndent(s.state, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(s.path), ".state-*")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if err = f.Chmod(0600); err == nil {
		_, err = f.Write(b)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(name, s.path); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(s.path))
}
func (s *Store) Update(fn func(*State) error) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.fault != nil {
		return s.fault
	}
	before, _ := json.Marshal(s.state)
	if err := fn(&s.state); err != nil {
		var restored State
		_ = json.Unmarshal(before, &restored)
		s.state = restored
		return err
	}
	totals := map[string]int64{}
	for _, task := range s.state.Tasks {
		key := task.PlanID
		if key == "" {
			key = task.ID
		}
		totals[key] += task.Budget.TaskSeconds
	}
	for _, task := range s.state.Tasks {
		key := task.PlanID
		if key == "" {
			key = task.ID
		}
		task.Budget.PlanSeconds = totals[key]
	}
	after, _ := json.Marshal(s.state)
	if bytes.Equal(before, after) {
		return nil
	}
	if err := s.persist(); err != nil {
		s.fault = fmt.Errorf("state persistence failed; restart after repair: %w", err)
		var restored State
		_ = json.Unmarshal(before, &restored)
		s.state = restored
		return err
	}
	return nil
}
func (s *Store) Snapshot() State {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, _ := json.Marshal(s.state)
	var v State
	_ = json.Unmarshal(b, &v)
	return v
}
func Emit(st *State, taskID, kind string, data any) {
	b, _ := json.Marshal(data)
	if len(b) > 256*1024 {
		b = json.RawMessage(`{"payloadOmitted":true,"reloadNativeMessages":true}`)
	}
	st.Sequence++
	st.Events = append(st.Events, Event{ID: st.Sequence, Type: kind, TaskID: taskID, Time: time.Now().UTC(), Data: b})
	total := 0
	start := len(st.Events)
	for start > 0 {
		size := len(st.Events[start-1].Data) + 128
		if total+size > 4*1024*1024 || len(st.Events)-start >= 1999 {
			break
		}
		total += size
		start--
	}
	if start > 0 {
		st.Events = append([]Event(nil), st.Events[start:]...)
	}
}
func Changed(st *State, t *Task) { t.UpdatedAt = time.Now().UTC(); Emit(st, t.ID, "task.updated", t) }

func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.lock != nil {
		return s.lock.Close()
	}
	return nil
}

// Transient deltas are replayable while this process lives. Pi persists native history.
func (s *Store) Event(taskID, kind string, data any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	Emit(&s.state, taskID, kind, data)
}

func (s *Store) NativeEvent(taskID, role, processID string, data any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	t := s.state.Tasks[taskID]
	if t == nil || t.DeletedAt != nil || t.Sessions[role] == nil || t.Sessions[role].ProcessID != processID {
		return
	}
	Emit(&s.state, taskID, "pi.event", data)
}

type Replay struct {
	Sequence int64
	First    int64
	Events   []Event
}

// ReplayAfter copies only immutable replay entries, avoiding whole-state clones per SSE poll.
func (s *Store) ReplayAfter(taskID string, after int64) Replay {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := Replay{Sequence: s.state.Sequence, Events: []Event{}}
	if len(s.state.Events) > 0 {
		r.First = s.state.Events[0].ID
	}
	for _, event := range s.state.Events {
		if event.ID > after && event.TaskID == taskID {
			r.Events = append(r.Events, event)
		}
	}
	return r
}
