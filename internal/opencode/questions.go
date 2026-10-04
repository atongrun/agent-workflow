package opencode

import (
	"context"
	"errors"
	"strings"
)

type Question struct {
	ID        string         `json:"id"`
	SessionID string         `json:"sessionID"`
	Questions []QuestionInfo `json:"questions"`
	Tool      *QuestionTool  `json:"tool,omitempty"`
}
type QuestionTool struct {
	MessageID string `json:"messageID"`
	CallID    string `json:"callID"`
}
type QuestionInfo struct {
	Question string           `json:"question"`
	Header   string           `json:"header"`
	Options  []QuestionOption `json:"options"`
	Multiple bool             `json:"multiple,omitempty"`
	Custom   *bool            `json:"custom,omitempty"`
}
type QuestionOption struct {
	Label       string `json:"label"`
	Description string `json:"description"`
}

func ValidQuestionID(id string) bool {
	if !strings.HasPrefix(id, "que_") || len(id) > 128 || len(id) <= 4 {
		return false
	}
	for _, c := range id {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_') {
			return false
		}
	}
	return true
}

// The native API has no idempotency key. The node must durably fence this POST.
func (c *Client) ReplyQuestion(ctx context.Context, directory, id string, answers [][]string) error {
	if !ValidQuestionID(id) {
		return errors.New("invalid native question ID")
	}
	var ok bool
	if err := c.request(ctx, "POST", "/question/"+id+"/reply", directory, map[string]any{"answers": answers}, &ok); err != nil {
		return err
	}
	if !ok {
		return errors.New("native question reply was not acknowledged")
	}
	return nil
}

// RejectQuestion dismisses one native request; caller must durably fence it.
func (c *Client) RejectQuestion(ctx context.Context, directory, id string) error {
	if !ValidQuestionID(id) {
		return errors.New("invalid native question ID")
	}
	var ok bool
	if err := c.request(ctx, "POST", "/question/"+id+"/reject", directory, nil, &ok); err != nil {
		return err
	}
	if !ok {
		return errors.New("native question rejection was not acknowledged")
	}
	return nil
}
