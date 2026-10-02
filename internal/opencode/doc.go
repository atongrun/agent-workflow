// Package opencode implements the native HTTP and SSE surface verified against
// OpenCode v1.18.34. See https://opencode.ai/docs/server/ and the release sources
// at https://github.com/anomalyco/opencode/tree/v1.18.34.
//
// The adapter requires an already-running loopback server, including on Windows.
// All instance-scoped requests carry the configured directory query parameter.
// Prompt acceptance, idle status and assistant prose are not execution verdicts.
// The native API does not promise idempotent prompt POSTs: callers must durably
// associate their request with a session and message before sending it once.
//
// Pending permission/question lists supplement SSE because events are not
// replayed after disconnect. No API in this package grants native permissions,
// answers questions, installs software, runs Git or creates credentials.
package opencode
