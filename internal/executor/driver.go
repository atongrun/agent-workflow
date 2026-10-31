// Package executor is the node-side plugin boundary for a local coding daemon.
// OpenCode keeps its existing client calls. Other daemons adapt to the same
// session, prompt, question, and event operations the node already sequences.
package executor

import (
	"context"
	"encoding/json"

	"github.com/atongrun/agent-workflow/internal/opencode"
)

// EventReader is the workspace event stream. Implementations must not replay a prompt.
type EventReader interface {
	Next() (opencode.Event, error)
	Close() error
}

// Driver is one local coding executor. The node still owns job durability,
// idempotency, and the rule that an uncertain prompt is never resent.
type Driver interface {
	Kind() string
	Health(context.Context) (opencode.Health, error)
	CreateSession(context.Context, string, string) (opencode.Session, error)
	Sessions(context.Context, string) ([]opencode.Session, error)
	Session(context.Context, string, string) (opencode.Session, error)
	PromptAsync(context.Context, string, string, string, string, ...*opencode.ModelSelection) error
	Statuses(context.Context, string) (map[string]opencode.Status, error)
	Messages(context.Context, string, string) ([]opencode.Message, error)
	PendingPermissions(context.Context, string) ([]json.RawMessage, error)
	PendingQuestions(context.Context, string) ([]json.RawMessage, error)
	Abort(context.Context, string, string) (bool, error)
	OpenEvents(context.Context, string) (EventReader, error)
	ReplyQuestion(context.Context, string, string, [][]string) error
	RejectQuestion(context.Context, string, string) error
}

// OpenCode adapts the existing loopback client without changing its calls.
type OpenCode struct {
	*opencode.Client
}

func (OpenCode) Kind() string { return "opencode" }

func (o OpenCode) OpenEvents(ctx context.Context, directory string) (EventReader, error) {
	return o.Client.OpenEvents(ctx, directory)
}
