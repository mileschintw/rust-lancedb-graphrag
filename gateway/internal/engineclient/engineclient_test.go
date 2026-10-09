package engineclient

import (
	"bytes"
	"context"
	"maps"
	"slices"
	"testing"

	pb "github.com/lancet/gateway/proto/lancet/v1"
	"google.golang.org/grpc"
)

// recordingStream captures every frame sent on an ingest stream.
type recordingStream struct {
	pb.LancetService_IngestDocumentClient
	frames []*pb.IngestDocumentRequest
}

func (s *recordingStream) Send(req *pb.IngestDocumentRequest) error {
	s.frames = append(s.frames, req)
	return nil
}

func (s *recordingStream) CloseAndRecv() (*pb.IngestDocumentResponse, error) {
	return &pb.IngestDocumentResponse{DocumentId: s.frames[0].DocumentId, Success: true}, nil
}

type recordingClient struct {
	pb.LancetServiceClient
	stream pb.LancetService_IngestDocumentClient
}

func (c *recordingClient) IngestDocument(context.Context, ...grpc.CallOption) (pb.LancetService_IngestDocumentClient, error) {
	return c.stream, nil
}

func TestIngestMetadataMap(t *testing.T) {
	chunkKeys := []string{"chunk_overlap", "chunk_size", "chunk_strategy"}

	t.Run("empty meta yields only the chunk keys", func(t *testing.T) {
		got := ingestMetadata("structure-aware", "500", "50", IngestMeta{})
		if keys := slices.Sorted(maps.Keys(got)); !slices.Equal(keys, chunkKeys) {
			t.Fatalf("keys = %v, want %v", keys, chunkKeys)
		}
		if got["chunk_strategy"] != "structure-aware" || got["chunk_size"] != "500" || got["chunk_overlap"] != "50" {
			t.Fatalf("chunk values = %#v", got)
		}
	})

	t.Run("full meta adds the three evidence keys", func(t *testing.T) {
		got := ingestMetadata("fixed-size", "800", "100", IngestMeta{DocTitle: "A title", Source: "A source", PublishedDate: "2023-10-07"})
		want := []string{"chunk_overlap", "chunk_size", "chunk_strategy", "doc_title", "published_date", "source"}
		if keys := slices.Sorted(maps.Keys(got)); !slices.Equal(keys, want) {
			t.Fatalf("keys = %v, want %v", keys, want)
		}
		if got["doc_title"] != "A title" || got["source"] != "A source" || got["published_date"] != "2023-10-07" {
			t.Fatalf("evidence values = %#v", got)
		}
	})

	t.Run("only non-empty fields are added", func(t *testing.T) {
		cases := []struct {
			name string
			meta IngestMeta
			key  string
		}{
			{"title only", IngestMeta{DocTitle: "T"}, "doc_title"},
			{"source only", IngestMeta{Source: "S"}, "source"},
			{"date only", IngestMeta{PublishedDate: "2023-10-07"}, "published_date"},
		}
		for _, tc := range cases {
			got := ingestMetadata("structure-aware", "500", "50", tc.meta)
			want := append([]string{tc.key}, chunkKeys...)
			slices.Sort(want)
			if keys := slices.Sorted(maps.Keys(got)); !slices.Equal(keys, want) {
				t.Fatalf("%s: keys = %v, want %v", tc.name, keys, want)
			}
		}
	})

	t.Run("first frame carries the evidence keys and later frames carry none", func(t *testing.T) {
		stream := &recordingStream{}
		engine := New(&recordingClient{stream: stream})
		payload := bytes.Repeat([]byte("x"), streamBufferSize+10)
		meta := IngestMeta{DocTitle: "T", Source: "S", PublishedDate: "2023-10-07"}
		outcome := engine.Ingest(t.Context(), "doc-1", "n.txt", "structure-aware", 500, 50, meta, bytes.NewReader(payload))
		if outcome.Err != nil {
			t.Fatalf("ingest error: %v", outcome.Err)
		}
		if len(stream.frames) < 2 {
			t.Fatalf("frames = %d, want at least 2", len(stream.frames))
		}
		first := stream.frames[0].Metadata
		if first["doc_title"] != "T" || first["source"] != "S" || first["published_date"] != "2023-10-07" || first["chunk_size"] != "500" {
			t.Fatalf("first frame metadata = %#v", first)
		}
		for i, frame := range stream.frames[1:] {
			if frame.Metadata != nil {
				t.Fatalf("frame %d carried metadata: %#v", i+1, frame.Metadata)
			}
		}
	})
}
