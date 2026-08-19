package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
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
	if ctx == nil {
		ctx = context.Background()
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

	if !json.Valid([]byte(env.ContextSnapshot)) {
		err := fmt.Errorf("checkpoint %s/%d has invalid JSON context_snapshot", env.TraceID, env.SequenceOrdinal)
		if s.logger != nil {
			s.logger.Error("save workflow checkpoint failed: invalid JSON", zap.String("trace_id", env.TraceID), zap.Uint64("sequence_ordinal", env.SequenceOrdinal), zap.Error(err))
		}
		return err
	}

	writeCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
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
	pending  []*CheckpointEnvelope
	mu       sync.Mutex
	sink     CheckpointSink
	closed   bool
	done     chan struct{}
}

func NewCheckpointDispatcher(sink CheckpointSink) *CheckpointDispatcher {
	d := &CheckpointDispatcher{
		primary:  make(chan *CheckpointEnvelope, 1),
		overflow: make([]*CheckpointEnvelope, 0, 4),
		pending:  make([]*CheckpointEnvelope, 0, 16),
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

func (d *CheckpointDispatcher) RetainPending(env *CheckpointEnvelope) error {
	if env == nil {
		return nil
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if len(d.pending) >= 16 {
		return errors.New("checkpoint pending queue is full")
	}
	d.pending = append(d.pending, env)
	return nil
}

func (d *CheckpointDispatcher) loop() {
	defer close(d.done)
	for {
		env := d.nextEnvelope()
		if env == nil {
			break
		}
		if d.sink != nil {
			if err := d.sink.SaveCheckpoint(context.Background(), env); err != nil {
				if ps, ok := d.sink.(*PostgresCheckpointSink); ok && ps.logger != nil {
					ps.logger.Warn("checkpoint dispatcher dropped envelope on sink error",
						zap.String("trace_id", env.TraceID),
						zap.Uint64("sequence_ordinal", env.SequenceOrdinal),
						zap.Error(err),
					)
				}
			}
		}
	}
}

func (d *CheckpointDispatcher) nextEnvelope() *CheckpointEnvelope {
	d.mu.Lock()

	// Drain primary first to preserve submission order
	select {
	case env, ok := <-d.primary:
		if ok {
			d.mu.Unlock()
			return env
		}
	default:
	}

	// Drain overflow in FIFO order
	if len(d.overflow) > 0 {
		env := d.overflow[0]
		d.overflow = d.overflow[1:]
		d.mu.Unlock()
		return env
	}

	// Drain pending in FIFO order
	if len(d.pending) > 0 {
		env := d.pending[0]
		d.pending = d.pending[1:]
		d.mu.Unlock()
		return env
	}

	if d.closed {
		d.mu.Unlock()
		return nil
	}

	d.mu.Unlock()
	env, ok := <-d.primary
	if !ok {
		d.mu.Lock()
		defer d.mu.Unlock()
		if len(d.overflow) > 0 {
			env = d.overflow[0]
			d.overflow = d.overflow[1:]
			return env
		}
		if len(d.pending) > 0 {
			env = d.pending[0]
			d.pending = d.pending[1:]
			return env
		}
		return nil
	}
	return env
}

func (d *CheckpointDispatcher) Close() {
	d.mu.Lock()
	if d.closed {
		d.mu.Unlock()
		<-d.done
		return
	}
	d.closed = true
	close(d.primary)
	d.mu.Unlock()

	<-d.done
}
