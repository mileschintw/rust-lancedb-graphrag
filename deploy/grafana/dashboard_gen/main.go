package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/grafana/grafana-foundation-sdk/go/common"
	"github.com/grafana/grafana-foundation-sdk/go/dashboard"
	"github.com/grafana/grafana-foundation-sdk/go/prometheus"
	"github.com/grafana/grafana-foundation-sdk/go/timeseries"
)

func main() {
	var outputPath string
	flag.StringVar(&outputPath, "output", "", "Output path for dashboard JSON")
	flag.Parse()

	if outputPath == "" {
		outputPath = filepath.Join("..", "dashboards", "lancet-rag-operations.json")
	}

	promType := "prometheus"
	promUID := "prometheus-datasource"
	dsRef := common.DataSourceRef{
		Type: &promType,
		Uid:  &promUID,
	}

	// 10 D-35 Metric Families
	p1 := timeseries.NewPanelBuilder().
		Title("RAG Query Duration").
		Description("Duration of end-to-end RAG queries by outcome").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("histogram_quantile(0.95, sum(rate(lancet_rag_query_duration_milliseconds_bucket[5m])) by (le, outcome))").
				LegendFormat("p95 - {{outcome}}"),
		).
		Unit("ms").
		Span(12).
		Height(8)

	p2 := timeseries.NewPanelBuilder().
		Title("Retrieval Path Failures").
		Description("Failures in dense/bm25/graph retrieval paths").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("sum by (path, kind) (rate(lancet_rag_retrieval_path_failures_total[5m]))").
				LegendFormat("{{path}} - {{kind}}"),
		).
		Span(12).
		Height(8)

	p3 := timeseries.NewPanelBuilder().
		Title("Answer Degraded Rate").
		Description("Degraded mode answers by basis").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("sum by (answer_basis) (rate(lancet_rag_answer_degraded_total[5m]))").
				LegendFormat("{{answer_basis}}"),
		).
		Span(12).
		Height(8)

	p4 := timeseries.NewPanelBuilder().
		Title("Citation Repairs").
		Description("Repaired or dropped citations by action").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("sum by (action) (rate(lancet_rag_citation_repairs_total[5m]))").
				LegendFormat("{{action}}"),
		).
		Span(12).
		Height(8)

	p5 := timeseries.NewPanelBuilder().
		Title("Generation Retries").
		Description("LLM generation retry attempts by outcome").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("sum by (outcome) (rate(lancet_rag_generation_retries_total[5m]))").
				LegendFormat("{{outcome}}"),
		).
		Span(12).
		Height(8)

	p6 := timeseries.NewPanelBuilder().
		Title("Evidence Set Size").
		Description("Number of evidence items assembled into prompts").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("histogram_quantile(0.95, sum(rate(lancet_rag_evidence_set_size_bucket[5m])) by (le))").
				LegendFormat("p95"),
		).
		Span(12).
		Height(8)

	p7 := timeseries.NewPanelBuilder().
		Title("Ingested Documents").
		Description("Ingestion throughput and outcomes for documents").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("sum by (outcome) (rate(lancet_ingest_documents_total[5m]))").
				LegendFormat("{{outcome}}"),
		).
		Span(12).
		Height(8)

	p8 := timeseries.NewPanelBuilder().
		Title("Ingested Chunks").
		Description("Ingestion throughput for text chunks").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("rate(lancet_ingest_chunks_total[5m])").
				LegendFormat("chunks/sec"),
		).
		Span(12).
		Height(8)

	p9 := timeseries.NewPanelBuilder().
		Title("Index Rebuild Duration").
		Description("Duration of background index rebuilds by outcome").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("histogram_quantile(0.95, sum(rate(lancet_index_rebuild_duration_milliseconds_bucket[5m])) by (le, outcome))").
				LegendFormat("p95 - {{outcome}}"),
		).
		Unit("ms").
		Span(12).
		Height(8)

	p10 := timeseries.NewPanelBuilder().
		Title("Corpus Generation").
		Description("Current corpus generation counter").
		Datasource(dsRef).
		WithTarget(
			prometheus.NewDataqueryBuilder().
				Expr("lancet_index_corpus_generation").
				LegendFormat("generation"),
		).
		Span(12).
		Height(8)

	builder := dashboard.NewDashboardBuilder("Lancet RAG Operations").
		Uid("lancet-rag-operations").
		Description("Operational metrics for Lancet RAG query, retrieval, generation and ingestion pipelines").
		Timezone("browser").
		Refresh("5s").
		Time("now-15m", "now").
		WithPanel(p1).
		WithPanel(p2).
		WithPanel(p3).
		WithPanel(p4).
		WithPanel(p5).
		WithPanel(p6).
		WithPanel(p7).
		WithPanel(p8).
		WithPanel(p9).
		WithPanel(p10)

	dash, err := builder.Build()
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to build dashboard: %v\n", err)
		os.Exit(1)
	}

	data, err := json.MarshalIndent(dash, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to marshal dashboard JSON: %v\n", err)
		os.Exit(1)
	}

	data = append(data, '\n')

	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "failed to create output dir: %v\n", err)
		os.Exit(1)
	}

	if err := os.WriteFile(outputPath, data, 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "failed to write dashboard JSON: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Dashboard written to %s\n", outputPath)
}
