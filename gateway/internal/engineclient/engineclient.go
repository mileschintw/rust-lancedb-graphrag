// Package engineclient owns the gateway's gRPC client onto the Lancet engine service,
// including the ingestion outcome shape, the Engine interface and GRPCEngine implementation,
// and the trailer-carrying error type that preserves engine-side error identity across the
// pre-stream boundary.
package engineclient

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strconv"
	"time"

	pb "github.com/lancet/gateway/proto/lancet/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

const streamBufferSize = 64 << 10

// IngestOutcome represents the result of a document ingestion attempt.
type IngestOutcome struct {
	Ambiguous bool
	Err       error
}

// Engine defines the client interface for interacting with the Lancet engine service.
type Engine interface {
	Ingest(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, src io.Reader) IngestOutcome
	IngestionStatus(context.Context, string) (*pb.GetIngestionStatusResponse, error)
	Ping(context.Context) (time.Duration, error)
	QueryRAG(context.Context, *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error)
}

// TrailerError wraps a gRPC error alongside its received response trailers.
type TrailerError struct {
	err     error
	trailer metadata.MD
}

// Error returns the underlying error message.
func (e TrailerError) Error() string {
	return e.err.Error()
}

// GRPCStatus returns the gRPC status representation of the underlying error.
func (e TrailerError) GRPCStatus() *status.Status {
	return status.Convert(e.err)
}

// Trailer returns the response metadata trailers received from the gRPC stream.
func (e TrailerError) Trailer() metadata.MD {
	return e.trailer
}

// NewTrailerError constructs a TrailerError wrapping err and trailer metadata.
func NewTrailerError(err error, trailer metadata.MD) TrailerError {
	return TrailerError{err: err, trailer: trailer}
}

// GRPCEngine implements Engine using a gRPC client connection.
type GRPCEngine struct {
	client pb.LancetServiceClient
}

// New creates a new GRPCEngine wrapping the provided LancetServiceClient.
func New(client pb.LancetServiceClient) *GRPCEngine {
	return &GRPCEngine{client: client}
}

// Ingest streams document bytes to the engine service in chunks.
func (e GRPCEngine) Ingest(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, src io.Reader) IngestOutcome {
	stream, err := e.client.IngestDocument(ctx)
	if err != nil {
		return IngestOutcome{Err: err}
	}
	buf := make([]byte, streamBufferSize)
	firstFrame := true
	for {
		n, readErr := src.Read(buf)
		if n > 0 {
			req := &pb.IngestDocumentRequest{
				DocumentId: id,
				ChunkData:  append([]byte(nil), buf[:n]...),
			}
			if firstFrame {
				firstFrame = false
				req.Filename = filename
				req.Metadata = map[string]string{
					"chunk_strategy": strategy,
					"chunk_size":     strconv.Itoa(chunkSize),
					"chunk_overlap":  strconv.Itoa(chunkOverlap),
				}
			}
			if err := stream.Send(req); err != nil {
				return IngestOutcome{Err: err}
			}
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return IngestOutcome{Err: readErr}
		}
	}
	resp, err := stream.CloseAndRecv()
	if err != nil {
		return IngestOutcome{Ambiguous: true, Err: err}
	}
	if !resp.GetSuccess() || resp.GetDocumentId() != id {
		return IngestOutcome{Err: fmt.Errorf("ingest rejected: success=%v, document_id=%q", resp.GetSuccess(), resp.GetDocumentId())}
	}
	return IngestOutcome{}
}

// IngestionStatus retrieves the processing status of a document from the engine service.
func (e GRPCEngine) IngestionStatus(ctx context.Context, id string) (*pb.GetIngestionStatusResponse, error) {
	return e.client.GetIngestionStatus(ctx, &pb.GetIngestionStatusRequest{DocumentId: id})
}

// Ping sends a ping request to the engine service and measures the round-trip latency.
func (e GRPCEngine) Ping(ctx context.Context) (time.Duration, error) {
	start := time.Now()
	_, err := e.client.Ping(ctx, &pb.PingRequest{Value: "ping"})
	return time.Since(start), err
}

// QueryRAG initiates a RAG query stream from the engine service, capturing response trailers on error.
func (e GRPCEngine) QueryRAG(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
	var trailer metadata.MD
	stream, err := e.client.QueryRAG(ctx, req, grpc.Trailer(&trailer))
	if err != nil {
		return nil, TrailerError{err: err, trailer: trailer}
	}
	return stream, nil
}
