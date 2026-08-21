// Package sse owns the server-sent-event framing for the /rag/query stream.
package sse

import (
	"encoding/json"
	"fmt"
	"net/http"

	pb "github.com/lancet/gateway/proto/lancet/v1"
)

// Stream error code constants.
const (
	ErrCodeStreamEOFWithoutTerminal = "STREAM_EOF_WITHOUT_TERMINAL"
	ErrCodeGRPCRecvError            = "GRPC_RECV_ERROR"
)

// eventStreamError is the SSE event name for a stream-level failure frame. The other six
// event names are assigned inline in WriteWorkflowEvent; this one is named so it is not
// buried inside a format string, where a rename would be invisible to a literal scan.
const eventStreamError = "stream_error"

// WriteStreamError formats and writes a stream_error event frame to the SSE stream.
func WriteStreamError(w http.ResponseWriter, rc *http.ResponseController, code, message string) {
	payload := map[string]any{
		"code":    code,
		"message": message,
	}
	dataBytes, err := json.Marshal(payload)
	if err != nil {
		return
	}
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", eventStreamError, dataBytes)
	_ = rc.Flush()
}

// WriteWorkflowEvent formats and writes a workflow event frame to the SSE stream.
//
// Caller contract: checkpoint events are NOT client-facing and are dropped here without
// being written. Persisting them is the caller's responsibility — the gateway handler
// submits them to the checkpoint dispatcher before delegating to this function. A caller
// that routes checkpoint events straight here silently loses them.
func WriteWorkflowEvent(w http.ResponseWriter, rc *http.ResponseController, ev *pb.WorkflowEvent) {
	if ev == nil || ev.GetCheckpoint() != nil {
		return
	}

	var eventType string
	var payload any

	switch e := ev.Event.(type) {
	case *pb.WorkflowEvent_NodeStarted:
		eventType = "node_started"
		payload = map[string]any{
			"node_name":        e.NodeStarted.GetNodeName(),
			"inputs_summary":   e.NodeStarted.GetInputsSummary(),
			"sequence_ordinal": ev.GetSequenceOrdinal(),
		}
	case *pb.WorkflowEvent_NodeCompleted:
		eventType = "node_completed"
		payload = map[string]any{
			"node_name":       e.NodeCompleted.GetNodeName(),
			"outputs_summary": e.NodeCompleted.GetOutputsSummary(),
			"duration_ms":     e.NodeCompleted.GetDurationMs(),
		}
	case *pb.WorkflowEvent_NodeFailed:
		eventType = "node_failed"
		payload = map[string]any{
			"node_name":     e.NodeFailed.GetNodeName(),
			"error_kind":    int32(e.NodeFailed.GetCategory()),
			"error_message": e.NodeFailed.GetMessage(),
			"retryable":     e.NodeFailed.GetRetryable(),
		}
	case *pb.WorkflowEvent_AnswerChunk:
		eventType = "answer_chunk"
		payload = map[string]any{
			"chunk_text": e.AnswerChunk.GetChunk(),
			"is_final":   e.AnswerChunk.GetIsFinal(),
		}
	case *pb.WorkflowEvent_FinalAnswer:
		eventType = "final_answer"
		payload = ToQueryRAGResponseDTO(e.FinalAnswer.GetResponse())
	case *pb.WorkflowEvent_WorkflowCompleted:
		eventType = "workflow_completed"
		wcPayload := map[string]any{
			"success":           e.WorkflowCompleted.GetSuccess(),
			"total_duration_ms": e.WorkflowCompleted.GetDurationMs(),
			"error_kind":        int32(e.WorkflowCompleted.GetErrorKind()),
			"error_message":     e.WorkflowCompleted.GetErrorMessage(),
		}
		if e.WorkflowCompleted.GetFinalResponse() != nil {
			wcPayload["final_response"] = ToQueryRAGResponseDTO(e.WorkflowCompleted.GetFinalResponse())
		} else {
			notices := make([]NoticeDTO, 0, len(e.WorkflowCompleted.GetNotices()))
			for _, n := range e.WorkflowCompleted.GetNotices() {
				if n == nil {
					continue
				}
				notices = append(notices, NoticeDTO{
					Code:      n.Code,
					Message:   n.Message,
					Severity:  int32(n.Severity),
					TypedCode: int32(n.TypedCode),
				})
			}
			wcPayload["notices"] = notices
		}
		var metaMap map[string]any
		if meta := e.WorkflowCompleted.GetMetadata(); meta != nil {
			metaMap = map[string]any{
				"started_at_ms":      meta.GetStartedAtMs(),
				"completed_at_ms":    meta.GetCompletedAtMs(),
				"reformulation_used": meta.GetReformulationUsed(),
				"vector_count":       meta.GetVectorCount(),
				"bm25_count":         meta.GetBm25Count(),
				"graph_node_count":   meta.GetGraphNodeCount(),
				"graph_edge_count":   meta.GetGraphEdgeCount(),
				"prompt_tokens":      meta.GetPromptTokens(),
				"completion_tokens":  meta.GetCompletionTokens(),
				"degraded_mode":      meta.GetDegradedMode(),
			}
		} else {
			metaMap = map[string]any{
				"started_at_ms":      int64(0),
				"completed_at_ms":    int64(0),
				"reformulation_used": false,
				"vector_count":       uint32(0),
				"bm25_count":         uint32(0),
				"graph_node_count":   uint32(0),
				"graph_edge_count":   uint32(0),
				"prompt_tokens":      uint32(0),
				"completion_tokens":  uint32(0),
				"degraded_mode":      false,
			}
		}
		wcPayload["metadata"] = metaMap
		payload = wcPayload
	default:
		return
	}

	dataBytes, err := json.Marshal(payload)
	if err != nil {
		return
	}

	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", eventType, dataBytes)
	_ = rc.Flush()
}
