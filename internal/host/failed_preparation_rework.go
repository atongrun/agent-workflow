package host

import (
	"github.com/atongrun/agent-workflow/internal/core"
	"github.com/atongrun/agent-workflow/internal/node"
)

// Proof is obtained only from the original authenticated durable Node receipt,
// outside the store lock. No caller payload or model text can supply it.
type failedPreparationProof struct {
	requestID, jobID, planHash        string
	targetRevision, lifecycleRevision int
}

func verifyFailedPreparation(t *core.Task, job *node.Job) *failedPreparationProof {
	e := t.Execution
	if t.DeletedAt != nil || t.PlanningProfile != core.RestrictedPlanning || t.ProjectID != "managed" || e == nil || e.Target == nil || e.Target.ProjectID != "managed" || e.Approved == nil || e.Status != "failed" || !e.DispatchAttempted || e.CancelRequested || e.SessionID != "" || e.OriginalSessionID != "" || e.StartedAt != nil || e.FinishedAt == nil || len(e.Evidence) != 0 {
		return nil
	}
	if job.ID != e.JobID || job.ID != node.JobID(e.RequestID) || job.RequestID != e.RequestID || job.TaskID != t.ID || job.ProjectID != e.Approved.ProjectID || job.Repository != e.Approved.Repository || job.Branch != e.Approved.Branch || job.Status != "failed" || job.SubmissionState != "queued" || job.SessionID != "" || job.StartedAt != nil || job.CompletedAt == nil || job.CancelRequested || job.TimedOut || job.NativeStatus != "" || job.NativeError != "" || !job.CompletedAt.Equal(*e.FinishedAt) || job.ExecutionSeconds != 0 || len(job.Evidence) != 0 || len(job.PendingPermissions) != 0 || len(job.PendingQuestions) != 0 {
		return nil
	}
	return &failedPreparationProof{e.RequestID, e.JobID, e.Approved.PlanHash, t.TargetRevision, t.LifecycleRevision}
}

func failedPreparationMatches(t *core.Task, proofs []*failedPreparationProof) bool {
	if len(proofs) != 1 || proofs[0] == nil || t.Execution == nil || t.Execution.Approved == nil || t.Execution.Target == nil || t.Execution.Status != "failed" || !t.Execution.DispatchAttempted || t.Execution.CancelRequested || t.Execution.SessionID != "" || t.Execution.OriginalSessionID != "" || t.Execution.StartedAt != nil || t.Execution.FinishedAt == nil || len(t.Execution.Evidence) != 0 || t.Settings.Reviewer == "pi" || t.Completion == nil || t.Completion.Verdict != "needs_changes" || t.Completion.ExecutionRequestID != t.Execution.RequestID {
		return false
	}
	p := proofs[0]
	return t.DeletedAt == nil && t.PlanningProfile == core.RestrictedPlanning && t.ProjectID == "managed" && t.Execution.Target.ProjectID == "managed" && p.requestID == t.Execution.RequestID && p.jobID == t.Execution.JobID && p.planHash == t.Execution.Approved.PlanHash && p.targetRevision == t.TargetRevision && p.lifecycleRevision == t.LifecycleRevision
}
