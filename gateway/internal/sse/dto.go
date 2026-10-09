// Package sse owns the server-sent-event framing and JSON response DTO surface for the /rag/query stream.
package sse

import (
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

// QueryRAGResponseDTO represents the JSON payload for a final RAG query response.
type QueryRAGResponseDTO struct {
	Answer              string                  `json:"answer"`
	Citations           []string                `json:"citations"`
	SessionID           string                  `json:"session_id"`
	AnswerBasis         int32                   `json:"answer_basis"`
	StructuredCitations []StructuredCitationDTO `json:"structured_citations"`
	Notices             []NoticeDTO             `json:"notices"`
	Snapshot            *RetrievalSnapshotDTO   `json:"snapshot"`
}

// StructuredCitationDTO represents a structured citation with chunk and document metadata.
type StructuredCitationDTO struct {
	ChunkID     string  `json:"chunk_id"`
	DocumentID  string  `json:"document_id"`
	Title       string  `json:"title"`
	SectionPath string  `json:"section_path"`
	Excerpt     string  `json:"excerpt"`
	IsTruncated bool    `json:"is_truncated"`
	Score       float64 `json:"score"`
	Rank        int32   `json:"rank"`
	ContentType string  `json:"content_type"`
}

// RetrievedChunkDTO is one chunk of the final retrieved set: a structured citation plus whether the
// graph contributed to its place there (06.3.4.1 D-81). The flag is always present, so a chunk the
// graph did not touch says `false`. It is a separate type so `structured_citations` keeps its
// nine-key contract: a citation names a chunk the answer cited, not how retrieval found it.
type RetrievedChunkDTO struct {
	StructuredCitationDTO
	GraphBoosted bool `json:"graph_boosted"`
}

// NoticeDTO represents a human- or machine-readable execution notice.
type NoticeDTO struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	Severity  int32  `json:"severity"`
	TypedCode int32  `json:"typed_code"`
}

// DocumentFilterDTO represents document ID and content type filters.
type DocumentFilterDTO struct {
	DocumentIDs  []string `json:"document_ids"`
	ContentTypes []string `json:"content_types"`
}

// RetrievalSnapshotDTO represents the retrieval parameters and state snapshot.
type RetrievalSnapshotDTO struct {
	IndexGeneration string              `json:"index_generation"`
	EmbeddingModel  string              `json:"embedding_model"`
	VectorWeight    float64             `json:"vector_weight"`
	Bm25Weight      float64             `json:"bm25_weight"`
	RrfK            int32               `json:"rrf_k"`
	CandidateLimit  int32               `json:"candidate_limit"`
	FinalLimit      int32               `json:"final_limit"`
	ActiveFilter    *DocumentFilterDTO  `json:"active_filter"`
	ResultHash      string              `json:"result_hash"`
	RetrievedChunks []RetrievedChunkDTO `json:"retrieved_chunks"`
	// RetrievalMode echoes the request's mode as a lowercase name (06.3.5 D-99). It is omitted
	// when the request set none, so a default snapshot keeps exactly its 10 keys.
	RetrievalMode string `json:"retrieval_mode,omitzero"`
	// PreTruncationRanking is the pre-rerank candidate ranking, present only when the request
	// opted in (06.3.5 D-100). IDs and ranks only; omitted otherwise.
	PreTruncationRanking []RankedCandidateDTO `json:"pre_truncation_ranking,omitzero"`
	// Levers is the canonical echo of the admitted levers as lowercase names, in ascending enum
	// number (06.3.6 D-136). It is omitted when no lever was admitted, so a default snapshot keeps
	// exactly its 10 keys.
	Levers []string `json:"levers,omitzero"`
}

// RankedCandidateDTO is one row of the pre-truncation ranking (06.3.5 D-100). Ranks are 1-based
// and a rank that is absent from its list is omitted. No chunk text is carried.
type RankedCandidateDTO struct {
	ChunkID      string `json:"chunk_id"`
	DocumentID   string `json:"document_id"`
	FusedRank    int32  `json:"fused_rank"`
	VectorRank   int32  `json:"vector_rank,omitzero"`
	Bm25Rank     int32  `json:"bm25_rank,omitzero"`
	GraphRank    int32  `json:"graph_rank,omitzero"`
	GraphBoosted bool   `json:"graph_boosted"`
}

// retrievalModeNames maps a non-zero RetrievalMode to its JSON name; the zero value has none.
var retrievalModeNames = map[pb.RetrievalMode]string{
	pb.RetrievalMode_RETRIEVAL_MODE_HYBRID:     "hybrid",
	pb.RetrievalMode_RETRIEVAL_MODE_DENSE_ONLY: "dense_only",
	pb.RetrievalMode_RETRIEVAL_MODE_BM25_ONLY:  "bm25_only",
}

// leverNames maps a non-zero Lever to its JSON name; the zero value has none.
var leverNames = map[pb.Lever]string{
	pb.Lever_LEVER_RERANK:               "rerank",
	pb.Lever_LEVER_EVIDENCE_METADATA:    "evidence_metadata",
	pb.Lever_LEVER_BINARY_ANSWER_FORMAT: "binary_answer_format",
	pb.Lever_LEVER_GRAPH_V2:             "graph_v2",
}

// toLeverNames maps the echoed lever enums to their names in the order the engine sent them
// (already ascending enum number). A value outside the known names is dropped.
func toLeverNames(in []pb.Lever) []string {
	if len(in) == 0 {
		return nil
	}
	out := make([]string, 0, len(in))
	for _, lever := range in {
		if name, ok := leverNames[lever]; ok {
			out = append(out, name)
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func toRankedCandidateDTOs(in []*pb.RankedCandidate) []RankedCandidateDTO {
	if len(in) == 0 {
		return nil
	}
	out := make([]RankedCandidateDTO, 0, len(in))
	for _, rc := range in {
		if rc == nil {
			continue
		}
		out = append(out, RankedCandidateDTO{
			ChunkID:      rc.ChunkId,
			DocumentID:   rc.DocumentId,
			FusedRank:    rc.FusedRank,
			VectorRank:   rc.VectorRank,
			Bm25Rank:     rc.Bm25Rank,
			GraphRank:    rc.GraphRank,
			GraphBoosted: rc.GraphBoosted,
		})
	}
	return out
}

func toStructuredCitationDTO(sc *pb.StructuredCitation) StructuredCitationDTO {
	return StructuredCitationDTO{
		ChunkID:     sc.ChunkId,
		DocumentID:  sc.DocumentId,
		Title:       sc.Title,
		SectionPath: sc.SectionPath,
		Excerpt:     sc.Excerpt,
		IsTruncated: sc.IsTruncated,
		Score:       sc.Score,
		Rank:        sc.Rank,
		ContentType: sc.ContentType,
	}
}

func toStructuredCitationDTOs(in []*pb.StructuredCitation) []StructuredCitationDTO {
	out := make([]StructuredCitationDTO, 0)
	for _, sc := range in {
		if sc == nil {
			continue
		}
		out = append(out, toStructuredCitationDTO(sc))
	}
	return out
}

func toRetrievedChunkDTOs(in []*pb.StructuredCitation) []RetrievedChunkDTO {
	out := make([]RetrievedChunkDTO, 0)
	for _, sc := range in {
		if sc == nil {
			continue
		}
		out = append(out, RetrievedChunkDTO{
			StructuredCitationDTO: toStructuredCitationDTO(sc),
			GraphBoosted:          sc.GraphBoosted,
		})
	}
	return out
}

// ToRetrievalSnapshotDTO maps a protobuf RetrievalSnapshot to its JSON DTO representation.
// Note: variant_count and variant_identities are deliberately omitted to preserve the exact
// 10-key payload contract asserted across gateway tests. A default request still yields exactly
// those 10 keys: retrieval_mode and pre_truncation_ranking appear only when the request set them.
func ToRetrievalSnapshotDTO(in *pb.RetrievalSnapshot) *RetrievalSnapshotDTO {
	if in == nil {
		return nil
	}
	var activeFilter *DocumentFilterDTO
	if in.ActiveFilter != nil {
		docIDs := make([]string, 0)
		if len(in.ActiveFilter.DocumentIds) > 0 {
			docIDs = in.ActiveFilter.DocumentIds
		}
		contentTypes := make([]string, 0)
		if len(in.ActiveFilter.ContentTypes) > 0 {
			contentTypes = in.ActiveFilter.ContentTypes
		}
		activeFilter = &DocumentFilterDTO{
			DocumentIDs:  docIDs,
			ContentTypes: contentTypes,
		}
	}
	return &RetrievalSnapshotDTO{
		IndexGeneration: in.IndexGeneration,
		EmbeddingModel:  in.EmbeddingModel,
		VectorWeight:    in.VectorWeight,
		Bm25Weight:      in.Bm25Weight,
		RrfK:            in.RrfK,
		CandidateLimit:  in.CandidateLimit,
		FinalLimit:      in.FinalLimit,
		ActiveFilter:    activeFilter,
		ResultHash:      in.ResultHash,
		RetrievedChunks: toRetrievedChunkDTOs(in.RetrievedChunks),
		// A mode outside the known names (a future enum value) maps to "" and is omitted.
		RetrievalMode:        retrievalModeNames[in.RetrievalMode],
		PreTruncationRanking: toRankedCandidateDTOs(in.PreTruncationRanking),
		Levers:               toLeverNames(in.Levers),
	}
}

// ToQueryRAGResponseDTO maps a protobuf QueryRAGResponse into its JSON DTO representation.
func ToQueryRAGResponseDTO(resp *pb.QueryRAGResponse) QueryRAGResponseDTO {
	if resp == nil {
		return QueryRAGResponseDTO{
			Citations:           make([]string, 0),
			StructuredCitations: make([]StructuredCitationDTO, 0),
			Notices:             make([]NoticeDTO, 0),
		}
	}
	citations := make([]string, 0)
	if len(resp.Citations) > 0 {
		citations = resp.Citations
	}

	structuredCitations := toStructuredCitationDTOs(resp.StructuredCitations)

	notices := make([]NoticeDTO, 0)
	for _, n := range resp.Notices {
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

	snapshot := ToRetrievalSnapshotDTO(resp.Snapshot)

	return QueryRAGResponseDTO{
		Answer:              resp.Answer,
		Citations:           citations,
		SessionID:           resp.SessionId,
		AnswerBasis:         int32(resp.AnswerBasis),
		StructuredCitations: structuredCitations,
		Notices:             notices,
		Snapshot:            snapshot,
	}
}
