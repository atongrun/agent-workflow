package node

import (
	"errors"
	"strings"

	"github.com/atongrun/agent-workflow/internal/executor"
	"github.com/atongrun/agent-workflow/internal/opencode"
	"github.com/atongrun/agent-workflow/internal/workbuddy"
)

func openExecutor(cfg Config) (executor.Driver, error) {
	kind := strings.TrimSpace(cfg.Executor)
	if kind == "" {
		kind = "opencode"
	}
	switch kind {
	case "opencode":
		client, err := opencode.New(opencode.Config{URL: cfg.OpenCodeURL, Username: cfg.OpenCodeUsername, Password: cfg.OpenCodePassword, HTTPClient: cfg.HTTPClient})
		if err != nil {
			return nil, err
		}
		return executor.OpenCode{Client: client}, nil
	case "workbuddy":
		return workbuddy.Open(workbuddy.OpenConfig{URL: cfg.WorkBuddyURL, Password: cfg.WorkBuddyPassword, PermissionMode: cfg.WorkBuddyPermissionMode, StateDir: cfg.StateDir, HTTPClient: cfg.HTTPClient})
	default:
		return nil, errors.New("executor must be opencode or workbuddy")
	}
}
