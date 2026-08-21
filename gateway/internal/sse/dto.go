// Package sse owns the server-sent-event framing and JSON response DTO surface for the /rag/query stream.
package sse

import (
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

// QueryRAGResponseDTO represents the JSON payload for a final RAG query response.
type QueryRAGResponseDTO struct {
	Answer              string                 `json:"answer"`
	Citations           []string               `json:"citations"`
	SessionID           string                 `json:"session_id"`
	AnswerBasis         int32                  `json:"answer_basis"`
	StructuredCitations []StructuredCitationDTO `json:"structured_citations"`
	Notices             []NoticeDTO            `json:"notices"`
	Snapshot            *RetrievalSnapshotDTO  `json:"snapshot"`
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

// NoticeDTO represents a human- or machine-readable execution notice.
type NoticeDTO struct {
	Code     string `json:"code"`
	Message  string `json:"message"`
	Severity int32  `json:"severity"`
}

// DocumentFilterDTO represents document ID and content type filters.
type DocumentFilterDTO struct {
	DocumentIDs  []string `json:"document_ids"`
	ContentTypes []string `json:"content_types"`
}

// RetrievalSnapshotDTO represents the retrieval parameters and state snapshot.
type RetrievalSnapshotDTO struct {
	IndexGeneration string             `json:"index_generation"`
	EmbeddingModel  string             `json:"embedding_model"`
	VectorWeight    float64            `json:"vector_weight"`
	Bm25Weight      float64            `json:"bm25_weight"`
	RrfK            int32              `json:"rrf_k"`
	CandidateLimit  int32              `json:"candidate_limit"`
	FinalLimit      int32              `json:"final_limit"`
	ActiveFilter    *DocumentFilterDTO `json:"active_filter"`
	ResultHash      string             `json:"result_hash"`
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

	structuredCitations := make([]StructuredCitationDTO, 0)
	for _, sc := range resp.StructuredCitations {
		if sc == nil {
			continue
		}
		structuredCitations = append(structuredCitations, StructuredCitationDTO{
			ChunkID:     sc.ChunkId,
			DocumentID:  sc.DocumentId,
			Title:       sc.Title,
			SectionPath: sc.SectionPath,
			Excerpt:     sc.Excerpt,
			IsTruncated: sc.IsTruncated,
			Score:       sc.Score,
			Rank:        sc.Rank,
			ContentType: sc.ContentType,
		})
	}

	notices := make([]NoticeDTO, 0)
	for _, n := range resp.Notices {
		if n == nil {
			continue
		}
		notices = append(notices, NoticeDTO{
			Code:     n.Code,
			Message:  n.Message,
			Severity: int32(n.Severity),
		})
	}

	var snapshot *RetrievalSnapshotDTO
	if resp.Snapshot != nil {
		var activeFilter *DocumentFilterDTO
		if resp.Snapshot.ActiveFilter != nil {
			docIDs := make([]string, 0)
			if len(resp.Snapshot.ActiveFilter.DocumentIds) > 0 {
				docIDs = resp.Snapshot.ActiveFilter.DocumentIds
			}
			contentTypes := make([]string, 0)
			if len(resp.Snapshot.ActiveFilter.ContentTypes) > 0 {
				contentTypes = resp.Snapshot.ActiveFilter.ContentTypes
			}
			activeFilter = &DocumentFilterDTO{
				DocumentIDs:  docIDs,
				ContentTypes: contentTypes,
			}
		}
		snapshot = &RetrievalSnapshotDTO{
			IndexGeneration: resp.Snapshot.IndexGeneration,
			EmbeddingModel:  resp.Snapshot.EmbeddingModel,
			VectorWeight:    resp.Snapshot.VectorWeight,
			Bm25Weight:      resp.Snapshot.Bm25Weight,
			RrfK:            resp.Snapshot.RrfK,
			CandidateLimit:  resp.Snapshot.CandidateLimit,
			FinalLimit:      resp.Snapshot.FinalLimit,
			ActiveFilter:    activeFilter,
			ResultHash:      resp.Snapshot.ResultHash,
		}
	}

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
