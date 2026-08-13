package main

import (
	"context"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.uber.org/zap"

	"github.com/lancet/gateway/db"
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

type CheckpointEnvelope struct {
	SessionID       string
	CorrelationID   string
	TraceID         string
	EventSequence   uint64
	NodeID          string
	CheckpointType  string
	SequenceOrdinal uint64
	ContextSnapshot string
	TimestampMs     int64
	CreatedAt       time.Time
}

func NewCheckpointEnvelopeFromEvent(ev *pb.WorkflowEvent) *CheckpointEnvelope {
	if ev == nil {
		return nil
	}
	cp := ev.GetCheckpoint()
	if cp == nil {
		return nil
	}
	return &CheckpointEnvelope{
		SessionID:       ev.GetSessionId(),
		CorrelationID:   ev.GetTraceId(),
		TraceID:         ev.GetTraceId(),
		EventSequence:   ev.GetSequenceOrdinal(),
		NodeID:          cp.GetCheckpointType(),
		CheckpointType:  cp.GetCheckpointType(),
		SequenceOrdinal: cp.GetSequenceOrdinal(),
		ContextSnapshot: cp.GetContextSnapshot(),
		TimestampMs:     ev.GetTimestampMs(),
		CreatedAt:       time.Now(),
	}
}

type DispatchResultKind int

const (
	DispatchAccepted DispatchResultKind = iota
	DispatchPending
)

type DispatchResult struct {
	Kind     DispatchResultKind
	Envelope *CheckpointEnvelope
}

type CheckpointSink interface {
	SaveCheckpoint(ctx context.Context, env *CheckpointEnvelope) error
}

type PostgresCheckpointSink struct {
	pool   *pgxpool.Pool
	logger *zap.Logger
}

func NewPostgresCheckpointSink(pool *pgxpool.Pool, logger *zap.Logger) *PostgresCheckpointSink {
	return &PostgresCheckpointSink{
		pool:   pool,
		logger: logger,
	}
}

func (s *PostgresCheckpointSink) SaveCheckpoint(ctx context.Context, env *CheckpointEnvelope) error {
	if env == nil {
		return nil
	}
	id := uuid.NewString()

	nodeName := env.NodeID
	if nodeName == "" {
		nodeName = env.CheckpointType
	}
	if nodeName == "" {
		nodeName = "unknown"
	}

	createdAt := env.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now()
	}

	writeCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	params := db.InsertWorkflowCheckpointParams{
		ID:              id,
		TraceID:         env.TraceID,
		SequenceOrdinal: int32(env.SequenceOrdinal),
		NodeName:        nodeName,
		ContextSnapshot: []byte(env.ContextSnapshot),
		CreatedAt:       pgtype.Timestamp{Time: createdAt, Valid: true},
	}

	_, err := db.New(s.pool).InsertWorkflowCheckpoint(writeCtx, params)
	if err != nil && s.logger != nil {
		s.logger.Error("save workflow checkpoint failed", zap.String("trace_id", env.TraceID), zap.Uint64("sequence_ordinal", env.SequenceOrdinal), zap.Error(err))
	}
	return err
}

type InMemoryCheckpointSink struct {
	mu          sync.Mutex
	checkpoints []*CheckpointEnvelope
}

func NewInMemoryCheckpointSink() *InMemoryCheckpointSink {
	return &InMemoryCheckpointSink{
		checkpoints: make([]*CheckpointEnvelope, 0),
	}
}

func (s *InMemoryCheckpointSink) SaveCheckpoint(ctx context.Context, env *CheckpointEnvelope) error {
	if env == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.checkpoints = append(s.checkpoints, env)
	return nil
}

func (s *InMemoryCheckpointSink) Checkpoints() []*CheckpointEnvelope {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]*CheckpointEnvelope, len(s.checkpoints))
	copy(out, s.checkpoints)
	return out
}


type CheckpointDispatcher struct {
	primary  chan *CheckpointEnvelope
	overflow []*CheckpointEnvelope
	mu       sync.Mutex
	sink     CheckpointSink
	closed   bool
	done     chan struct{}
}

func NewCheckpointDispatcher(sink CheckpointSink) *CheckpointDispatcher {
	d := &CheckpointDispatcher{
		primary:  make(chan *CheckpointEnvelope, 1),
		overflow: make([]*CheckpointEnvelope, 0, 4),
		sink:     sink,
		done:     make(chan struct{}),
	}
	go d.loop()
	return d
}

func (d *CheckpointDispatcher) Submit(env *CheckpointEnvelope) DispatchResult {
	if env == nil {
		return DispatchResult{Kind: DispatchAccepted}
	}
	d.mu.Lock()
	defer d.mu.Unlock()

	if d.closed {
		return DispatchResult{Kind: DispatchPending, Envelope: env}
	}

	select {
	case d.primary <- env:
		return DispatchResult{Kind: DispatchAccepted}
	default:
		if len(d.overflow) < 4 {
			d.overflow = append(d.overflow, env)
			return DispatchResult{Kind: DispatchAccepted}
		}
		return DispatchResult{Kind: DispatchPending, Envelope: env}
	}
}

func (d *CheckpointDispatcher) loop() {
	defer close(d.done)
	for {
		env := d.nextEnvelope()
		if env == nil {
			break
		}
		if d.sink != nil {
			_ = d.sink.SaveCheckpoint(context.Background(), env)
		}
	}
}

func (d *CheckpointDispatcher) nextEnvelope() *CheckpointEnvelope {
	d.mu.Lock()

	if len(d.overflow) > 0 {
		env := d.overflow[0]
		d.overflow = d.overflow[1:]
		d.mu.Unlock()
		return env
	}

	select {
	case env, ok := <-d.primary:
		d.mu.Unlock()
		if !ok {
			return nil
		}
		return env
	default:
		if d.closed {
			d.mu.Unlock()
			return nil
		}
	}

	d.mu.Unlock()
	env, ok := <-d.primary
	if !ok {
		return nil
	}
	return env
}

func (d *CheckpointDispatcher) Close() {
	d.mu.Lock()
	if d.closed {
		d.mu.Unlock()
		return
	}
	d.closed = true
	close(d.primary)
	d.mu.Unlock()

	<-d.done
}
