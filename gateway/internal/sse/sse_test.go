package sse

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	pb "github.com/lancet/gateway/proto/lancet/v1"
)

// writeEvent runs WriteWorkflowEvent against a recorder and returns the raw frame.
func writeEvent(t *testing.T, ev *pb.WorkflowEvent) string {
	t.Helper()
	rec := httptest.NewRecorder()
	WriteWorkflowEvent(rec, http.NewResponseController(rec), ev)
	return rec.Body.String()
}

// splitFrame splits an SSE frame into its event name and its data payload.
func splitFrame(t *testing.T, frame string) (string, string) {
	t.Helper()
	if !strings.HasSuffix(frame, "\n\n") {
		t.Fatalf("frame is not terminated by a blank line: %q", frame)
	}
	lines := strings.Split(strings.TrimSuffix(frame, "\n\n"), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected exactly an event line and a data line, got %d: %q", len(lines), frame)
	}
	name, ok := strings.CutPrefix(lines[0], "event: ")
	if !ok {
		t.Fatalf("first line is not an event line: %q", lines[0])
	}
	data, ok := strings.CutPrefix(lines[1], "data: ")
	if !ok {
		t.Fatalf("second line is not a data line: %q", lines[1])
	}
	return name, data
}

// TestWriteWorkflowEventNames pins the seven client-facing SSE event names and the
// JSON keys of each payload. These are the wire contract Phase 6.3's harness parses.
func TestWriteWorkflowEventNames(t *testing.T) {
	tests := []struct {
		name      string
		event     *pb.WorkflowEvent
		wantEvent string
		wantKeys  []string
	}{
		{
			name: "node_started",
			event: &pb.WorkflowEvent{
				SequenceOrdinal: 7,
				Event: &pb.WorkflowEvent_NodeStarted{
					NodeStarted: &pb.NodeStartedEvent{NodeName: "ReformulateQuery", InputsSummary: "inputs"},
				},
			},
			wantEvent: "node_started",
			wantKeys:  []string{"node_name", "inputs_summary", "sequence_ordinal"},
		},
		{
			name: "node_completed",
			event: &pb.WorkflowEvent{
				Event: &pb.WorkflowEvent_NodeCompleted{
					NodeCompleted: &pb.NodeCompletedEvent{NodeName: "Retrieve", OutputsSummary: "outputs", DurationMs: 42},
				},
			},
			wantEvent: "node_completed",
			wantKeys:  []string{"node_name", "outputs_summary", "duration_ms"},
		},
		{
			name: "node_failed",
			event: &pb.WorkflowEvent{
				Event: &pb.WorkflowEvent_NodeFailed{
					NodeFailed: &pb.NodeFailedEvent{
						NodeName:  "ExtractGraphContext",
						Category:  pb.NodeErrorKind_NODE_ERROR_KIND_TIMEOUT,
						Message:   "graph timed out",
						Retryable: false,
					},
				},
			},
			wantEvent: "node_failed",
			wantKeys:  []string{"node_name", "error_kind", "error_message", "retryable"},
		},
		{
			name: "answer_chunk",
			event: &pb.WorkflowEvent{
				Event: &pb.WorkflowEvent_AnswerChunk{
					AnswerChunk: &pb.AnswerChunkEvent{Chunk: "hello", IsFinal: false},
				},
			},
			wantEvent: "answer_chunk",
			wantKeys:  []string{"chunk_text", "is_final"},
		},
		{
			name: "final_answer",
			event: &pb.WorkflowEvent{
				Event: &pb.WorkflowEvent_FinalAnswer{
					FinalAnswer: &pb.FinalAnswerEvent{Response: &pb.QueryRAGResponse{Answer: "hi"}},
				},
			},
			wantEvent: "final_answer",
			wantKeys:  []string{"answer", "citations", "session_id", "answer_basis", "structured_citations", "notices", "snapshot"},
		},
		{
			name: "workflow_completed",
			event: &pb.WorkflowEvent{
				Event: &pb.WorkflowEvent_WorkflowCompleted{
					WorkflowCompleted: &pb.WorkflowCompletedEvent{Success: true, DurationMs: 120},
				},
			},
			wantEvent: "workflow_completed",
			wantKeys:  []string{"success", "total_duration_ms", "error_kind", "error_message"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			gotEvent, data := splitFrame(t, writeEvent(t, tc.event))
			if gotEvent != tc.wantEvent {
				t.Fatalf("event name: got %q, want %q", gotEvent, tc.wantEvent)
			}
			var payload map[string]any
			if err := json.Unmarshal([]byte(data), &payload); err != nil {
				t.Fatalf("unmarshal payload: %v (data=%q)", err, data)
			}
			for _, key := range tc.wantKeys {
				if _, ok := payload[key]; !ok {
					t.Fatalf("payload missing key %q: %q", key, data)
				}
			}
		})
	}
}

// TestWriteWorkflowEventNoticePrecedence pins AI-SPEC §4.3: workflow_completed carries
// notices ONLY when final_response is absent. Two populated lists can diverge, and the
// Phase 6.3 client hardcodes this precedence.
func TestWriteWorkflowEventNoticePrecedence(t *testing.T) {
	notices := []*pb.Notice{
		{Code: "GRAPH_TIMEOUT", Message: "Graph query timed out", Severity: pb.NoticeSeverity_NOTICE_SEVERITY_WARNING},
		{Code: "GRAPH_DEGRADED", Message: "Answer produced without graph context", Severity: pb.NoticeSeverity_NOTICE_SEVERITY_WARNING},
	}

	t.Run("notices present when final_response is nil", func(t *testing.T) {
		_, data := splitFrame(t, writeEvent(t, &pb.WorkflowEvent{
			Event: &pb.WorkflowEvent_WorkflowCompleted{
				WorkflowCompleted: &pb.WorkflowCompletedEvent{
					Success:       false,
					ErrorKind:     pb.NodeErrorKind_NODE_ERROR_KIND_TIMEOUT,
					FinalResponse: nil,
					Notices:       notices,
				},
			},
		}))

		var payload struct {
			FinalResponse *QueryRAGResponseDTO `json:"final_response"`
			Notices       *[]NoticeDTO         `json:"notices"`
		}
		if err := json.Unmarshal([]byte(data), &payload); err != nil {
			t.Fatalf("unmarshal payload: %v", err)
		}
		if payload.FinalResponse != nil {
			t.Fatal("final_response must be absent on a failure terminal")
		}
		if payload.Notices == nil {
			t.Fatalf("notices must be present when final_response is nil: %q", data)
		}
		if len(*payload.Notices) != 2 {
			t.Fatalf("notice count: got %d, want 2", len(*payload.Notices))
		}
		if (*payload.Notices)[0].Code != "GRAPH_TIMEOUT" || (*payload.Notices)[1].Code != "GRAPH_DEGRADED" {
			t.Fatalf("notice codes or order changed: %#v", *payload.Notices)
		}
	})

	t.Run("notices omitted when final_response is present", func(t *testing.T) {
		_, data := splitFrame(t, writeEvent(t, &pb.WorkflowEvent{
			Event: &pb.WorkflowEvent_WorkflowCompleted{
				WorkflowCompleted: &pb.WorkflowCompletedEvent{
					Success:       true,
					FinalResponse: &pb.QueryRAGResponse{Answer: "hi"},
					Notices:       notices,
				},
			},
		}))

		var payload map[string]json.RawMessage
		if err := json.Unmarshal([]byte(data), &payload); err != nil {
			t.Fatalf("unmarshal payload: %v", err)
		}
		if _, ok := payload["final_response"]; !ok {
			t.Fatalf("final_response must be present on a success terminal: %q", data)
		}
		if _, ok := payload["notices"]; ok {
			t.Fatalf("workflow_completed must not carry a top-level notices list alongside final_response: %q", data)
		}
	})
}

// TestWriteWorkflowEventDropsNonClientFrames pins that nil, checkpoint and unknown-variant
// events produce no bytes at all rather than a malformed frame.
func TestWriteWorkflowEventDropsNonClientFrames(t *testing.T) {
	tests := []struct {
		name  string
		event *pb.WorkflowEvent
	}{
		{name: "nil event", event: nil},
		{
			name: "checkpoint event",
			event: &pb.WorkflowEvent{
				Event: &pb.WorkflowEvent_Checkpoint{Checkpoint: &pb.CheckpointEvent{CheckpointType: "node_boundary", SequenceOrdinal: 3}},
			},
		},
		{name: "event with no variant set", event: &pb.WorkflowEvent{SequenceOrdinal: 1}},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if body := writeEvent(t, tc.event); body != "" {
				t.Fatalf("expected no bytes written, got %q", body)
			}
		})
	}
}

// TestWriteStreamErrorCodes pins the two stream_error codes and the frame shape.
func TestWriteStreamErrorCodes(t *testing.T) {
	tests := []struct {
		name    string
		code    string
		message string
	}{
		{name: "eof without terminal", code: ErrCodeStreamEOFWithoutTerminal, message: "stream ended before workflow_completed"},
		{name: "grpc recv error", code: ErrCodeGRPCRecvError, message: "rpc error: code = Unavailable"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			WriteStreamError(rec, http.NewResponseController(rec), tc.code, tc.message)

			gotEvent, data := splitFrame(t, rec.Body.String())
			if gotEvent != "stream_error" {
				t.Fatalf("event name: got %q, want %q", gotEvent, "stream_error")
			}
			var payload struct {
				Code    string `json:"code"`
				Message string `json:"message"`
			}
			if err := json.Unmarshal([]byte(data), &payload); err != nil {
				t.Fatalf("unmarshal payload: %v", err)
			}
			if payload.Code != tc.code {
				t.Fatalf("code: got %q, want %q", payload.Code, tc.code)
			}
			if payload.Message != tc.message {
				t.Fatalf("message: got %q, want %q", payload.Message, tc.message)
			}
		})
	}
}

// TestStreamErrorCodeConstants pins the literal values of the exported codes. The
// constants and any remaining raw literals at call sites must not drift apart.
func TestStreamErrorCodeConstants(t *testing.T) {
	if ErrCodeStreamEOFWithoutTerminal != "STREAM_EOF_WITHOUT_TERMINAL" {
		t.Fatalf("ErrCodeStreamEOFWithoutTerminal changed: %q", ErrCodeStreamEOFWithoutTerminal)
	}
	if ErrCodeGRPCRecvError != "GRPC_RECV_ERROR" {
		t.Fatalf("ErrCodeGRPCRecvError changed: %q", ErrCodeGRPCRecvError)
	}
}

// TestToQueryRAGResponseDTOEmptySlices pins that the repeated fields marshal as [] and
// never as null, for a nil response and for a response with no repeated entries.
func TestToQueryRAGResponseDTOEmptySlices(t *testing.T) {
	tests := []struct {
		name string
		resp *pb.QueryRAGResponse
	}{
		{name: "nil response", resp: nil},
		{name: "empty response", resp: &pb.QueryRAGResponse{}},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			data, err := json.Marshal(ToQueryRAGResponseDTO(tc.resp))
			if err != nil {
				t.Fatalf("marshal DTO: %v", err)
			}
			for _, key := range []string{"citations", "structured_citations", "notices"} {
				if strings.Contains(string(data), `"`+key+`":null`) {
					t.Fatalf("%s marshalled as null rather than []: %s", key, data)
				}
			}
			if !strings.Contains(string(data), `"snapshot":null`) {
				t.Fatalf("snapshot must stay nullable when absent: %s", data)
			}
		})
	}
}

// TestToQueryRAGResponseDTOMapping pins the scalar and nested mapping, including the
// active_filter passthrough inside the retrieval snapshot.
func TestToQueryRAGResponseDTOMapping(t *testing.T) {
	dto := ToQueryRAGResponseDTO(&pb.QueryRAGResponse{
		Answer:    "the answer",
		Citations: []string{"doc1", "doc2"},
		SessionId: "session-1",
		StructuredCitations: []*pb.StructuredCitation{
			{ChunkId: "chunk-1", DocumentId: "doc-1", Title: "Title", Score: 0.5, Rank: 1, ContentType: "text/markdown"},
			nil, // nil entries are skipped, not mapped to a zero citation
		},
		Notices: []*pb.Notice{{Code: "GRAPH_DEGRADED", Message: "degraded", Severity: pb.NoticeSeverity_NOTICE_SEVERITY_WARNING}},
		Snapshot: &pb.RetrievalSnapshot{
			IndexGeneration: "gen-1",
			EmbeddingModel:  "bge-small",
			RrfK:            60,
			ResultHash:      "abc123",
			ActiveFilter:    &pb.DocumentFilter{DocumentIds: []string{"doc-1"}},
		},
	})

	if dto.Answer != "the answer" || dto.SessionID != "session-1" {
		t.Fatalf("scalar mapping changed: %#v", dto)
	}
	if len(dto.Citations) != 2 {
		t.Fatalf("citations: got %d, want 2", len(dto.Citations))
	}
	if len(dto.StructuredCitations) != 1 {
		t.Fatalf("nil structured citations must be skipped: got %d, want 1", len(dto.StructuredCitations))
	}
	if dto.StructuredCitations[0].ChunkID != "chunk-1" || dto.StructuredCitations[0].Rank != 1 {
		t.Fatalf("structured citation mapping changed: %#v", dto.StructuredCitations[0])
	}
	if len(dto.Notices) != 1 || dto.Notices[0].Code != "GRAPH_DEGRADED" {
		t.Fatalf("notice mapping changed: %#v", dto.Notices)
	}
	if dto.Snapshot == nil {
		t.Fatal("snapshot must be mapped when present")
	}
	if dto.Snapshot.IndexGeneration != "gen-1" || dto.Snapshot.RrfK != 60 || dto.Snapshot.ResultHash != "abc123" {
		t.Fatalf("snapshot mapping changed: %#v", dto.Snapshot)
	}
	if dto.Snapshot.ActiveFilter == nil || len(dto.Snapshot.ActiveFilter.DocumentIDs) != 1 {
		t.Fatalf("active filter mapping changed: %#v", dto.Snapshot.ActiveFilter)
	}
	if dto.Snapshot.ActiveFilter.ContentTypes == nil {
		t.Fatal("content_types must be an empty slice rather than nil")
	}
}

// TestQueryRAGResponseDTOJSONKeys pins every JSON key on the response DTO. Plan 06-07
// adds fields here; this fails loudly if an existing key is renamed or dropped.
func TestQueryRAGResponseDTOJSONKeys(t *testing.T) {
	data, err := json.Marshal(QueryRAGResponseDTO{})
	if err != nil {
		t.Fatalf("marshal DTO: %v", err)
	}
	var payload map[string]json.RawMessage
	if err := json.Unmarshal(data, &payload); err != nil {
		t.Fatalf("unmarshal DTO: %v", err)
	}

	want := []string{"answer", "citations", "session_id", "answer_basis", "structured_citations", "notices", "snapshot"}
	for _, key := range want {
		if _, ok := payload[key]; !ok {
			t.Fatalf("response DTO missing key %q: %s", key, data)
		}
	}
	if len(payload) != len(want) {
		t.Fatalf("response DTO key count: got %d (%s), want %d — update this test and the wire contract deliberately", len(payload), data, len(want))
	}
}

func TestSSEWorkflowCompletedMetadataForwarding(t *testing.T) {
	meta := &pb.WorkflowMetadata{
		StartedAtMs:       1700000000000,
		CompletedAtMs:     1700000001500,
		ReformulationUsed: true,
		VectorCount:       5,
		Bm25Count:         3,
		GraphNodeCount:    4,
		GraphEdgeCount:    6,
		PromptTokens:      120,
		CompletionTokens:  45,
		DegradedMode:      true,
	}

	ev := &pb.WorkflowEvent{
		Event: &pb.WorkflowEvent_WorkflowCompleted{
			WorkflowCompleted: &pb.WorkflowCompletedEvent{
				Success:    true,
				DurationMs: 1500,
				Metadata:   meta,
			},
		},
	}

	raw := writeEvent(t, ev)
	name, data := splitFrame(t, raw)
	if name != "workflow_completed" {
		t.Fatalf("expected event name 'workflow_completed', got %q", name)
	}

	var payload struct {
		Success    bool           `json:"success"`
		DurationMs int64          `json:"duration_ms"`
		Metadata   map[string]any `json:"metadata"`
	}
	if err := json.Unmarshal([]byte(data), &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}

	if payload.Metadata == nil {
		t.Fatal("expected metadata map in workflow_completed payload")
	}

	if payload.Metadata["started_at_ms"] != float64(1700000000000) {
		t.Errorf("started_at_ms: got %v, want 1700000000000", payload.Metadata["started_at_ms"])
	}
	if payload.Metadata["completed_at_ms"] != float64(1700000001500) {
		t.Errorf("completed_at_ms: got %v, want 1700000001500", payload.Metadata["completed_at_ms"])
	}
	if payload.Metadata["reformulation_used"] != true {
		t.Errorf("reformulation_used: got %v, want true", payload.Metadata["reformulation_used"])
	}
	if payload.Metadata["vector_count"] != float64(5) {
		t.Errorf("vector_count: got %v, want 5", payload.Metadata["vector_count"])
	}
	if payload.Metadata["bm25_count"] != float64(3) {
		t.Errorf("bm25_count: got %v, want 3", payload.Metadata["bm25_count"])
	}
	if payload.Metadata["graph_node_count"] != float64(4) {
		t.Errorf("graph_node_count: got %v, want 4", payload.Metadata["graph_node_count"])
	}
	if payload.Metadata["graph_edge_count"] != float64(6) {
		t.Errorf("graph_edge_count: got %v, want 6", payload.Metadata["graph_edge_count"])
	}
	if payload.Metadata["prompt_tokens"] != float64(120) {
		t.Errorf("prompt_tokens: got %v, want 120", payload.Metadata["prompt_tokens"])
	}
	if payload.Metadata["completion_tokens"] != float64(45) {
		t.Errorf("completion_tokens: got %v, want 45", payload.Metadata["completion_tokens"])
	}
	if payload.Metadata["degraded_mode"] != true {
		t.Errorf("degraded_mode: got %v, want true", payload.Metadata["degraded_mode"])
	}
}

func TestRetrievalSnapshotDTOCarriesRetrievedChunks(t *testing.T) {
	resp := &pb.QueryRAGResponse{
		Answer:    "answer",
		SessionId: "session-1",
		StructuredCitations: []*pb.StructuredCitation{
			{
				ChunkId:     "chunk-cited-1",
				DocumentId:  "doc-1",
				Title:       "Doc 1",
				SectionPath: "Sec 1",
				Excerpt:     "cited excerpt",
				IsTruncated: false,
				Score:       0.99,
				Rank:        1,
				ContentType: "text/plain",
			},
		},
		Snapshot: &pb.RetrievalSnapshot{
			IndexGeneration: "gen-1",
			EmbeddingModel:  "model-1",
			VectorWeight:    1.0,
			Bm25Weight:      0.8,
			RrfK:            60,
			CandidateLimit:  32,
			FinalLimit:      8,
			ResultHash:      "hash-1",
			RetrievedChunks: []*pb.StructuredCitation{
				{
					ChunkId:     "chunk-retrieved-1",
					DocumentId:  "doc-1",
					Title:       "Doc 1",
					SectionPath: "Sec 1",
					Excerpt:     "retrieved excerpt 1",
					IsTruncated: false,
					Score:       0.95,
					Rank:        1,
					ContentType: "text/plain",
				},
				{
					ChunkId:     "chunk-retrieved-2",
					DocumentId:  "doc-2",
					Title:       "Doc 2",
					SectionPath: "Sec 2",
					Excerpt:     "retrieved excerpt 2",
					IsTruncated: true,
					Score:       0.85,
					Rank:        2,
					ContentType: "text/markdown",
				},
				{
					ChunkId:     "chunk-retrieved-3",
					DocumentId:  "doc-3",
					Title:       "Doc 3",
					SectionPath: "Sec 3",
					Excerpt:     "retrieved excerpt 3",
					IsTruncated: false,
					Score:       0.75,
					Rank:        3,
					ContentType: "text/html",
				},
			},
		},
	}

	dto := ToQueryRAGResponseDTO(resp)
	if dto.Snapshot == nil {
		t.Fatal("expected non-nil Snapshot")
	}
	if len(dto.Snapshot.RetrievedChunks) != 3 {
		t.Fatalf("retrieved_chunks length: got %d, want 3", len(dto.Snapshot.RetrievedChunks))
	}
	if len(dto.StructuredCitations) != 1 {
		t.Fatalf("structured_citations length: got %d, want 1", len(dto.StructuredCitations))
	}
	if dto.Snapshot.RetrievedChunks[0].ChunkID == dto.StructuredCitations[0].ChunkID {
		t.Fatal("retrieved_chunks and structured_citations must be independent")
	}

	for i, chunk := range dto.Snapshot.RetrievedChunks {
		src := resp.Snapshot.RetrievedChunks[i]
		if chunk.ChunkID != src.ChunkId ||
			chunk.DocumentID != src.DocumentId ||
			chunk.Title != src.Title ||
			chunk.SectionPath != src.SectionPath ||
			chunk.Excerpt != src.Excerpt ||
			chunk.IsTruncated != src.IsTruncated ||
			chunk.Score != src.Score ||
			chunk.Rank != src.Rank ||
			chunk.ContentType != src.ContentType {
			t.Fatalf("retrieved chunk %d mismatch: got %#v, want %#v", i, chunk, src)
		}
	}
}

func TestRetrievedChunksSerialisesAsEmptyArray(t *testing.T) {
	// Case 1: Empty retrieved chunks serialises as [] not null
	resp := &pb.QueryRAGResponse{
		Snapshot: &pb.RetrievalSnapshot{
			IndexGeneration: "gen-1",
			RetrievedChunks: []*pb.StructuredCitation{},
		},
	}
	dto := ToQueryRAGResponseDTO(resp)
	data, err := json.Marshal(dto)
	if err != nil {
		t.Fatalf("marshal DTO: %v", err)
	}
	str := string(data)
	if !strings.Contains(str, `"retrieved_chunks":[]`) {
		t.Fatalf("expected \"retrieved_chunks\":[] in JSON, got %s", str)
	}
	if strings.Contains(str, `"retrieved_chunks":null`) {
		t.Fatalf("unexpected \"retrieved_chunks\":null in JSON: %s", str)
	}

	// Case 2: Nil entry inside slice is skipped without panic
	respWithNil := &pb.QueryRAGResponse{
		Snapshot: &pb.RetrievalSnapshot{
			RetrievedChunks: []*pb.StructuredCitation{
				nil,
				{
					ChunkId: "chunk-valid",
					Rank:    1,
				},
				nil,
			},
		},
	}
	dtoWithNil := ToQueryRAGResponseDTO(respWithNil)
	if len(dtoWithNil.Snapshot.RetrievedChunks) != 1 || dtoWithNil.Snapshot.RetrievedChunks[0].ChunkID != "chunk-valid" {
		t.Fatalf("expected 1 valid chunk after skipping nil entries, got %#v", dtoWithNil.Snapshot.RetrievedChunks)
	}

	// Case 3: Nil snapshot produces nil Snapshot pointer
	respNilSnapshot := &pb.QueryRAGResponse{
		Snapshot: nil,
	}
	dtoNilSnapshot := ToQueryRAGResponseDTO(respNilSnapshot)
	if dtoNilSnapshot.Snapshot != nil {
		t.Fatalf("expected nil Snapshot pointer, got %#v", dtoNilSnapshot.Snapshot)
	}
}
