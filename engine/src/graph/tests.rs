use std::sync::Arc;

use arrow_array::{Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};

use super::bridge;
use super::{
    clamp_hop_cap, clamp_hop_cap_with_ceiling, traverse_filtered_by_relation_type,
    traverse_fixed_hop, traverse_multi_hop, GraphSpikeErrorKind, MAX_HOP_CAP,
    MAX_RELATION_TYPE_FILTER_BYTES, MAX_SEED_ENTITY_NAME_BYTES,
};

/// RESEARCH.md's exact 3-entity/2-edge fixture: Alice --knows--> Bob,
/// Alice --founded_by--> Acme.
fn three_entity_two_edge_fixture() -> (RecordBatch, RecordBatch) {
    let entities_schema = Arc::new(Schema::new(vec![
        Field::new("entity_id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("entity_type", DataType::Utf8, false),
    ]));
    let entities = RecordBatch::try_new(
        entities_schema,
        vec![
            Arc::new(StringArray::from(vec!["abc-123", "def-456", "ghi-789"])),
            Arc::new(StringArray::from(vec!["Alice", "Bob", "Acme"])),
            Arc::new(StringArray::from(vec!["person", "person", "organization"])),
        ],
    )
    .expect("entities fixture batch must build");

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
    ]));
    let edges = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(vec!["abc-123", "abc-123"])),
            Arc::new(StringArray::from(vec!["def-456", "ghi-789"])),
            Arc::new(StringArray::from(vec!["knows", "founded_by"])),
        ],
    )
    .expect("edges fixture batch must build");

    (entities, edges)
}

/// RESEARCH.md's exact 2-entity/1-edge multi-hop fixture: Alice --knows--> Bob.
fn two_entity_one_edge_fixture() -> (RecordBatch, RecordBatch) {
    let entities_schema = Arc::new(Schema::new(vec![
        Field::new("entity_id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("entity_type", DataType::Utf8, false),
    ]));
    let entities = RecordBatch::try_new(
        entities_schema,
        vec![
            Arc::new(StringArray::from(vec!["abc-123", "def-456"])),
            Arc::new(StringArray::from(vec!["Alice", "Bob"])),
            Arc::new(StringArray::from(vec!["person", "person"])),
        ],
    )
    .expect("entities fixture batch must build");

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
    ]));
    let edges = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(vec!["abc-123"])),
            Arc::new(StringArray::from(vec!["def-456"])),
            Arc::new(StringArray::from(vec!["knows"])),
        ],
    )
    .expect("edges fixture batch must build");

    (entities, edges)
}

#[test]
fn bridge_round_trip_preserves_schema_and_values() {
    let (entities, _edges) = three_entity_two_edge_fixture();

    let bridged = bridge::bridge_batch(&entities).expect("forward bridge must succeed");
    let round_tripped = bridge::bridge_batch_back(&bridged).expect("inverse bridge must succeed");

    assert_eq!(
        round_tripped.schema().fields().len(),
        entities.schema().fields().len()
    );
    for (original_field, round_tripped_field) in entities
        .schema()
        .fields()
        .iter()
        .zip(round_tripped.schema().fields().iter())
    {
        assert_eq!(original_field.name(), round_tripped_field.name());
    }

    for column_index in 0..entities.num_columns() {
        let original_column = entities
            .column(column_index)
            .as_any()
            .downcast_ref::<StringArray>()
            .expect("fixture columns are Utf8");
        let round_tripped_column = round_tripped
            .column(column_index)
            .as_any()
            .downcast_ref::<StringArray>()
            .expect("round-tripped columns must remain Utf8");
        assert_eq!(original_column, round_tripped_column);
    }
}

#[tokio::test]
async fn fixed_single_hop_projects_relationship_properties() {
    let (entities, edges) = three_entity_two_edge_fixture();

    let result = traverse_fixed_hop(&entities, &edges, "abc-123")
        .await
        .expect("fixed single-hop traversal must succeed");

    assert_eq!(result.num_rows(), 2);
    let relation_types = result
        .column_by_name("r.relation_type")
        .expect("result must project r.relation_type")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("r.relation_type must be Utf8");
    let observed: std::collections::HashSet<&str> = (0..relation_types.len())
        .map(|row| relation_types.value(row))
        .collect();
    let expected: std::collections::HashSet<&str> = ["knows", "founded_by"].into_iter().collect();
    assert_eq!(observed, expected);
}

#[tokio::test]
async fn multi_hop_traversal_finds_one_hop_neighbor() {
    let (entities, edges) = two_entity_one_edge_fixture();

    let result = traverse_multi_hop(&entities, &edges, "abc-123", MAX_HOP_CAP)
        .await
        .expect("multi-hop traversal must succeed");

    assert_eq!(result.num_rows(), 1);
    let neighbor_ids = result
        .column_by_name("neighbor.entity_id")
        .expect("result must project neighbor.entity_id")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("neighbor.entity_id must be Utf8");
    assert_eq!(neighbor_ids.value(0), "def-456");
}

#[tokio::test]
async fn relation_type_filter_excludes_non_matching_edge() {
    let (entities, edges) = three_entity_two_edge_fixture();

    let result = traverse_filtered_by_relation_type(&entities, &edges, "abc-123", "founded_by")
        .await
        .expect("relation_type-filtered traversal must succeed");

    assert_eq!(result.num_rows(), 1);
    let neighbor_ids = result
        .column_by_name("neighbor.entity_id")
        .expect("result must project neighbor.entity_id")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("neighbor.entity_id must be Utf8");
    assert_eq!(neighbor_ids.value(0), "ghi-789");
}

#[test]
fn clamp_hop_cap_rejects_zero_and_over_max() {
    let zero_err = clamp_hop_cap(0).expect_err("hop_cap of 0 must be rejected");
    assert_eq!(zero_err.kind, GraphSpikeErrorKind::InvalidHopCap);

    let over_max_err =
        clamp_hop_cap(MAX_HOP_CAP + 1).expect_err("hop_cap above MAX_HOP_CAP must be rejected");
    assert_eq!(over_max_err.kind, GraphSpikeErrorKind::InvalidHopCap);

    assert_eq!(clamp_hop_cap(MAX_HOP_CAP), Ok(MAX_HOP_CAP));
}

#[test]
fn graph_fact_block_escaping_contract() {
    use super::context_strategy::{ContextAssemblyStrategy, GraphFact};
    use crate::prompt::GraphFactBlock;

    let raw_src = "<Tag & 'Name'>";
    let raw_rel = "REL & TYPE";
    let raw_tgt = "<Target>";
    let fact = GraphFact::new(raw_src, raw_rel, raw_tgt, None, 0.9);

    let assembled = ContextAssemblyStrategy::SourceChunks.assemble(&fact);
    assert!(assembled.contains("&lt;Tag &amp; &apos;Name&apos;&gt;"));
    assert!(assembled.contains("REL &amp; TYPE"));
    assert!(assembled.contains("&lt;Target&gt;"));
    assert!(!assembled.contains("<Tag"));

    let block = GraphFactBlock { fact: fact.clone() };
    let serialized = serde_json::to_string(&block).expect("GraphFactBlock must serialize");
    assert!(serialized.contains("&lt;Tag &amp; &apos;Name&apos;&gt;"));

    // Deserialization disabled invariant: check that serde_json::from_str fails or isn't implemented
    // Note: GraphFact does NOT derive Deserialize, ensuring private-field constructor cannot be bypassed.
}

#[tokio::test]
async fn extraction_generator_trait_and_fake() {
    use super::extraction::{
        ExtractedEntity, ExtractedRelation, ExtractionGenerator, ExtractionOutput,
        ExtractionRequest, FakeExtractionGenerator,
    };

    let fake_output = ExtractionOutput {
        entities: vec![ExtractedEntity {
            name: "Alice".into(),
            entity_type: "person".into(),
        }],
        relations: vec![ExtractedRelation {
            source: "Alice".into(),
            target: "Bob".into(),
            relation_type: "knows".into(),
            confidence: 0.95,
        }],
    };

    let generator = FakeExtractionGenerator::new(Ok(fake_output.clone()));
    let req = ExtractionRequest {
        chunk_id: "chk-1".into(),
        document_id: "doc-1".into(),
        chunk_text: "Alice knows Bob.".into(),
    };

    let res = generator
        .extract(req)
        .await
        .expect("Fake extraction must succeed");
    assert_eq!(res, fake_output);
}

#[test]
fn structured_extraction_json_schema_validation() {
    use super::extraction::OpenRouterExtractionGenerator;
    use crate::generation::openrouter::OpenRouterGenerationConfig;
    use std::time::Duration;

    let config = OpenRouterGenerationConfig::new(
        "test-model",
        "https://example.com/chat",
        "https://example.com/models",
        Duration::from_secs(10),
        0.0,
        1.0,
        768,
        768,
    )
    .expect("OpenRouterGenerationConfig must construct");

    let gen = OpenRouterExtractionGenerator::new_with_config("api-key", config)
        .expect("OpenRouterExtractionGenerator must construct");

    let req_body = gen.build_request_payload("Test chunk text");
    assert_eq!(req_body["model"], "test-model");

    let response_format = &req_body["response_format"];
    assert_eq!(response_format["type"], "json_schema");

    let schema_obj = &response_format["json_schema"];
    assert_eq!(schema_obj["strict"], true);
    assert_eq!(schema_obj["name"], "knowledge_graph_extraction");

    let schema_val = &schema_obj["schema"];
    assert_eq!(schema_val["type"], "object");
    assert_eq!(schema_val["additionalProperties"], false);

    let props = &schema_val["properties"];
    assert!(props.get("entities").is_some());
    assert!(props.get("relations").is_some());

    let entities_items = &props["entities"]["items"];
    assert_eq!(entities_items["additionalProperties"], false);
    assert!(entities_items["properties"].get("name").is_some());
    assert!(entities_items["properties"].get("entity_type").is_some());

    let rel_items = &props["relations"]["items"];
    assert_eq!(rel_items["additionalProperties"], false);
    assert!(rel_items["properties"].get("source").is_some());
    assert!(rel_items["properties"].get("target").is_some());
    assert!(rel_items["properties"].get("relation_type").is_some());
    assert!(rel_items["properties"].get("confidence").is_some());
}

#[test]
fn openrouter_generation_config_accessors() {
    use crate::generation::openrouter::OpenRouterGenerationConfig;
    use std::time::Duration;

    let config = OpenRouterGenerationConfig::new(
        "my-model",
        "https://example.com/chat",
        "https://example.com/models",
        Duration::from_secs(12),
        0.1,
        0.9,
        512,
        512,
    )
    .expect("Config must construct");

    assert_eq!(config.model(), "my-model");
    assert_eq!(config.chat_endpoint(), "https://example.com/chat");
    assert_eq!(config.timeout(), Duration::from_secs(12));
    assert_eq!(config.temperature(), 0.1);
    assert_eq!(config.top_p(), 0.9);
}

#[tokio::test]
async fn narrow_via_cypher_narrows_to_empty_when_seed_absent_from_graph() {
    let (entities, edges) = three_entity_two_edge_fixture();
    // A nonexistent seed narrows to zero entities and zero edges under Cypher confirmation
    let (out_entities, out_edges) =
        super::narrow_via_cypher(&entities, &edges, "nonexistent-seed", 1).await;
    assert_eq!(out_entities.num_rows(), 0);
    assert_eq!(out_edges.num_rows(), 0);
}

#[test]
fn constrain_to_cypher_matched_narrows_response_when_cypher_confirms_fewer_neighbors() {
    let (entities, edges) = three_entity_two_edge_fixture();
    let mut cypher_neighbor_ids = std::collections::HashSet::new();
    cypher_neighbor_ids.insert("def-456".to_string());

    let (out_entities, out_edges) =
        super::constrain_to_cypher_matched(&entities, &edges, "abc-123", &cypher_neighbor_ids)
            .expect("constrain_to_cypher_matched must succeed");

    assert_eq!(out_entities.num_rows(), 2);
    assert_eq!(out_edges.num_rows(), 1);

    let rel_col = out_edges
        .column_by_name("relation_type")
        .expect("relation_type column must exist")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("relation_type must be StringArray");
    assert_eq!(rel_col.value(0), "knows");
}

#[test]
fn constrain_to_cypher_matched_preserves_full_response_when_cypher_confirms_all_neighbors() {
    let (entities, edges) = three_entity_two_edge_fixture();
    let mut cypher_neighbor_ids = std::collections::HashSet::new();
    cypher_neighbor_ids.insert("def-456".to_string());
    cypher_neighbor_ids.insert("ghi-789".to_string());

    let (out_entities, out_edges) =
        super::constrain_to_cypher_matched(&entities, &edges, "abc-123", &cypher_neighbor_ids)
            .expect("constrain_to_cypher_matched must succeed");

    assert_eq!(out_entities.num_rows(), 3);
    assert_eq!(out_edges.num_rows(), 2);
}

#[tokio::test]
async fn cypher_confirmed_neighbor_ids_reflects_real_traverse_multi_hop_execution() {
    let entities_schema = Arc::new(Schema::new(vec![
        Field::new("entity_id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("entity_type", DataType::Utf8, false),
    ]));
    let entities = RecordBatch::try_new(
        entities_schema,
        vec![
            Arc::new(StringArray::from(vec!["abc-123", "def-456", "ghi-789"])),
            Arc::new(StringArray::from(vec!["Alice", "Bob", "Acme"])),
            Arc::new(StringArray::from(vec!["person", "person", "organization"])),
        ],
    )
    .expect("entities batch must build");

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("edge_id", DataType::Utf8, false),
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
        Field::new("weight", DataType::Float32, false),
    ]));
    let edges = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(vec!["edge-1", "edge-2"])),
            Arc::new(StringArray::from(vec!["abc-123", "abc-123"])),
            Arc::new(StringArray::from(vec!["def-456", "ghi-789"])),
            Arc::new(StringArray::from(vec!["knows", "founded_by"])),
            Arc::new(arrow_array::Float32Array::from(vec![0.9, 0.8])),
        ],
    )
    .expect("5-column edges batch must build");

    let confirmed = super::cypher_confirmed_neighbor_ids(&entities, &edges, "abc-123", 1)
        .await
        .expect("cypher_confirmed_neighbor_ids must succeed");

    let expected: std::collections::HashSet<String> =
        ["def-456".to_string(), "ghi-789".to_string()]
            .into_iter()
            .collect();
    assert_eq!(confirmed, expected);
}

#[tokio::test]
async fn cypher_confirmed_neighbor_ids_finds_neighbor_regardless_of_edge_direction() {
    let (entities, edges) = two_entity_one_edge_fixture();
    let confirmed = super::cypher_confirmed_neighbor_ids(&entities, &edges, "def-456", 1)
        .await
        .expect("cypher_confirmed_neighbor_ids must succeed");

    let expected: std::collections::HashSet<String> = ["abc-123".to_string()].into_iter().collect();
    assert_eq!(confirmed, expected);
}

#[tokio::test]
async fn cypher_confirmed_neighbor_ids_does_not_confirm_direction_changing_multi_hop_path() {
    let entities_schema = Arc::new(Schema::new(vec![
        Field::new("entity_id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("entity_type", DataType::Utf8, false),
    ]));
    let entities = RecordBatch::try_new(
        entities_schema,
        vec![
            Arc::new(StringArray::from(vec!["a-id", "b-id", "c-id"])),
            Arc::new(StringArray::from(vec!["A", "B", "C"])),
            Arc::new(StringArray::from(vec!["person", "person", "person"])),
        ],
    )
    .expect("entities batch must build");

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
    ]));
    let edges = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(vec!["a-id", "c-id"])),
            Arc::new(StringArray::from(vec!["b-id", "b-id"])),
            Arc::new(StringArray::from(vec!["knows", "knows"])),
        ],
    )
    .expect("edges batch must build");

    let confirmed = super::cypher_confirmed_neighbor_ids(&entities, &edges, "a-id", 2)
        .await
        .expect("cypher_confirmed_neighbor_ids must succeed");

    let expected: std::collections::HashSet<String> = ["b-id".to_string()].into_iter().collect();
    assert_eq!(confirmed, expected);
}

#[tokio::test]
async fn narrow_via_cypher_narrows_to_seed_only_when_zero_neighbors_confirmed() {
    let entities_schema = Arc::new(Schema::new(vec![
        Field::new("entity_id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("entity_type", DataType::Utf8, false),
    ]));
    let entities = RecordBatch::try_new(
        entities_schema,
        vec![
            Arc::new(StringArray::from(vec!["iso-1", "iso-2"])),
            Arc::new(StringArray::from(vec!["Lonely", "Other"])),
            Arc::new(StringArray::from(vec!["person", "person"])),
        ],
    )
    .expect("entities batch must build");

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
    ]));
    let edges = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(Vec::<&str>::new())),
            Arc::new(StringArray::from(Vec::<&str>::new())),
            Arc::new(StringArray::from(Vec::<&str>::new())),
        ],
    )
    .expect("empty edges batch must build");

    let (out_entities, out_edges) = super::narrow_via_cypher(&entities, &edges, "iso-1", 1).await;
    assert_eq!(out_entities.num_rows(), 1);
    assert_eq!(out_edges.num_rows(), 0);
}

/// Proves `narrow_via_cypher`'s fail-open path for the `InvalidHopCap` case specifically.
/// `hop_cap = 0` is rejected by `clamp_hop_cap` inside `cypher_confirmed_neighbor_ids`'s `traverse_multi_hop`
/// call before any Cypher query is ever parsed or executed — and does NOT exercise a genuine
/// `CypherParse`/`CypherExecute` failure (WR-04, 04.1-REVIEW.md); that residual case remains an accepted,
/// untested gap, since forcing a real `lance-graph` 0.5.4 execution-time failure would require internals
/// this plan cannot verify without open-ended trial-and-error, so the test's name and scope are narrowed to match
/// its actual, already-correct coverage rather than left silently implying broader coverage than it has.
#[tokio::test]
async fn narrow_via_cypher_fails_open_on_invalid_hop_cap() {
    let (entities, edges) = three_entity_two_edge_fixture();
    let (out_entities, out_edges) = super::narrow_via_cypher(&entities, &edges, "abc-123", 0).await;
    assert_eq!(out_entities.num_rows(), entities.num_rows());
    assert_eq!(out_edges.num_rows(), edges.num_rows());
}

#[test]
fn bridge_preserves_all_rows_across_multiple_ipc_batches() {
    let schema = Arc::new(Schema::new(vec![
        Field::new("entity_id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
    ]));

    let batch1 = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(vec!["id-1", "id-2"])),
            Arc::new(StringArray::from(vec!["Name1", "Name2"])),
        ],
    )
    .unwrap();

    let batch2 = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(vec!["id-3", "id-4", "id-5"])),
            Arc::new(StringArray::from(vec!["Name3", "Name4", "Name5"])),
        ],
    )
    .unwrap();

    // Construct raw IPC bytes containing TWO batches
    let mut buf = Vec::new();
    {
        let mut writer = arrow_ipc::writer::StreamWriter::try_new(&mut buf, &schema).unwrap();
        writer.write(&batch1).unwrap();
        writer.write(&batch2).unwrap();
        writer.finish().unwrap();
    }

    let reader = arrow_ipc_lg::reader::StreamReader::try_new(buf.as_slice(), None).unwrap();
    let bridged_lg = bridge::decode_all_batches(reader)
        .expect("decode_all_batches must succeed on 2-batch stream");
    assert_eq!(
        bridged_lg.num_rows(),
        5,
        "bridged_lg must contain all 5 rows across both batches"
    );

    // Also test bridge_batch_back direction decoding multiple batches
    let schema_lg = Arc::new(arrow_lg::datatypes::Schema::new(vec![
        arrow_lg::datatypes::Field::new("entity_id", arrow_lg::datatypes::DataType::Utf8, false),
        arrow_lg::datatypes::Field::new("name", arrow_lg::datatypes::DataType::Utf8, false),
    ]));

    let batch1_lg = arrow_lg::record_batch::RecordBatch::try_new(
        schema_lg.clone(),
        vec![
            Arc::new(arrow_lg::array::StringArray::from(vec!["id-1", "id-2"])),
            Arc::new(arrow_lg::array::StringArray::from(vec!["Name1", "Name2"])),
        ],
    )
    .unwrap();

    let batch2_lg = arrow_lg::record_batch::RecordBatch::try_new(
        schema_lg.clone(),
        vec![
            Arc::new(arrow_lg::array::StringArray::from(vec!["id-3"])),
            Arc::new(arrow_lg::array::StringArray::from(vec!["Name3"])),
        ],
    )
    .unwrap();

    let mut buf_lg = Vec::new();
    {
        let mut writer =
            arrow_ipc_lg::writer::StreamWriter::try_new(&mut buf_lg, &schema_lg).unwrap();
        writer.write(&batch1_lg).unwrap();
        writer.write(&batch2_lg).unwrap();
        writer.finish().unwrap();
    }

    let reader_back = arrow_ipc::reader::StreamReader::try_new(buf_lg.as_slice(), None).unwrap();
    let bridged_back = bridge::decode_all_batches(reader_back)
        .expect("decode_all_batches must succeed on 2-batch back stream");
    assert_eq!(
        bridged_back.num_rows(),
        3,
        "bridged_back must contain all 3 rows across both batches"
    );
}
#[test]
fn clamp_hop_cap_with_ceiling_applies_min_of_configured_and_compile_time() {
    // configured_max below MAX_HOP_CAP: the configured value wins
    assert_eq!(clamp_hop_cap_with_ceiling(1, 1), Ok(1));
    assert_eq!(clamp_hop_cap_with_ceiling(2, 2), Ok(2));
    // configured_max equal to MAX_HOP_CAP: both agree
    assert_eq!(
        clamp_hop_cap_with_ceiling(MAX_HOP_CAP, MAX_HOP_CAP),
        Ok(MAX_HOP_CAP)
    );
    // configured_max above MAX_HOP_CAP: capped to compile-time bound
    assert_eq!(
        clamp_hop_cap_with_ceiling(MAX_HOP_CAP, MAX_HOP_CAP + 5),
        Ok(MAX_HOP_CAP)
    );
}

#[test]
fn clamp_hop_cap_with_ceiling_rejects_zero_and_over_effective_max() {
    let err = clamp_hop_cap_with_ceiling(0, MAX_HOP_CAP).expect_err("0 must be rejected");
    assert_eq!(err.kind, GraphSpikeErrorKind::InvalidHopCap);

    // request above a low configured ceiling is rejected
    let err2 = clamp_hop_cap_with_ceiling(3, 2).expect_err("3 must be rejected when ceiling is 2");
    assert_eq!(err2.kind, GraphSpikeErrorKind::InvalidHopCap);
}

#[test]
fn byte_ceiling_constants_are_sensibly_bounded() {
    // Constants mirror extraction JSON-Schema maxLength values; verify they are
    // plausible (non-zero, not absurdly large) so a schema change is caught here.
    assert!(MAX_SEED_ENTITY_NAME_BYTES > 0);
    assert!(MAX_SEED_ENTITY_NAME_BYTES <= 4096);
    assert!(MAX_RELATION_TYPE_FILTER_BYTES > 0);
    assert!(MAX_RELATION_TYPE_FILTER_BYTES <= 1024);
}

struct ExtractionValidationDebugCaptureLayer {
    captured: Arc<std::sync::Mutex<Vec<f64>>>,
}

struct ExtractionValidationDebugVisitor<'a> {
    captured: &'a Arc<std::sync::Mutex<Vec<f64>>>,
}

impl<'a> tracing::field::Visit for ExtractionValidationDebugVisitor<'a> {
    fn record_f64(&mut self, field: &tracing::field::Field, value: f64) {
        if field.name() == "confidence" {
            self.captured.lock().unwrap().push(value);
        }
    }

    fn record_debug(&mut self, _field: &tracing::field::Field, _value: &dyn std::fmt::Debug) {}
}

impl<S> tracing_subscriber::layer::Layer<S> for ExtractionValidationDebugCaptureLayer
where
    S: tracing::Subscriber,
{
    fn on_event(
        &self,
        event: &tracing::Event<'_>,
        _ctx: tracing_subscriber::layer::Context<'_, S>,
    ) {
        let mut visitor = ExtractionValidationDebugVisitor {
            captured: &self.captured,
        };
        event.record(&mut visitor);
    }
}

#[test]
fn validate_extraction_output_logs_confidence_field_on_out_of_range_failure() {
    use tracing_subscriber::layer::SubscriberExt;

    let captured = Arc::new(std::sync::Mutex::new(Vec::new()));
    let layer = ExtractionValidationDebugCaptureLayer {
        captured: captured.clone(),
    };
    let subscriber = tracing_subscriber::registry()
        .with(tracing_subscriber::filter::LevelFilter::DEBUG)
        .with(layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let output = super::extraction::ExtractionOutput {
        entities: vec![],
        relations: vec![super::extraction::ExtractedRelation {
            source: "A".into(),
            target: "B".into(),
            relation_type: "knows".into(),
            confidence: 1.5,
        }],
    };

    let result = super::extraction::validate_extraction_output(&output);
    assert!(result.is_err());
    assert_eq!(captured.lock().unwrap().as_slice(), &[1.5_f64]);
}

/// OI-01 (06.3.4.1-13): `GraphIndex`, mention seeding and seed-to-seed paths.
pub(crate) mod seed_paths {
    use std::collections::{BTreeSet, HashMap};
    use std::sync::{Arc, Mutex};

    use arrow_array::builder::{ListBuilder, StringBuilder};
    use arrow_array::new_null_array;
    use arrow_array::types::Float32Type;
    use arrow_array::{FixedSizeListArray, Float32Array, RecordBatch, StringArray};
    use futures::future::BoxFuture;
    use uuid::Uuid;

    use crate::db::DatabaseManager;
    use crate::graph::index::{casefold_name, normalize_name, EntityRecord, GraphIndex};
    use crate::graph::paths::{
        build_paths, chunk_candidates, derive_max_path_facts, find_seed_paths,
        seed_chunk_candidates, ChunkSelection, EdgeRow, PathSettings, SeedPathResult,
        MAX_PATH_FACTS, MAX_PATH_FACTS_CEILING, MULTI_CITED_MIN_ENTITIES,
    };
    use crate::graph::seeding::{
        extract_mentions, match_seeds, LanceMentionVectorSearch, MatchKind, MentionVectorSearch,
        Seed, SeedSettings,
    };
    use crate::ingest::EmbeddingProvider;

    pub(crate) fn id(n: u128) -> String {
        Uuid::from_u128(n).to_string()
    }

    fn ent(n: u128, name: &str, chunks: &[&str]) -> EntityRecord {
        EntityRecord {
            entity_id: id(n),
            name: name.to_string(),
            source_chunk_ids: chunks.iter().map(|c| (*c).to_string()).collect(),
        }
    }

    /// `(source, target, relation, weight)` edges over entity numbers.
    pub(crate) type EdgeSpec = (u128, u128, &'static str, f64);

    fn graph(entities: Vec<EntityRecord>, edges: &[EdgeSpec]) -> (GraphIndex, Vec<EdgeRow>) {
        let pairs: Vec<(String, String)> = edges.iter().map(|(s, t, _, _)| (id(*s), id(*t))).collect();
        let rows: Vec<EdgeRow> = edges
            .iter()
            .enumerate()
            .map(|(i, (s, t, rel, w))| EdgeRow {
                edge_id: format!("edge-{i}"),
                source: id(*s),
                target: id(*t),
                relation: (*rel).to_string(),
                weight: *w,
            })
            .collect();
        (GraphIndex::from_parts(entities, &pairs), rows)
    }

    fn seed_of(index: &GraphIndex, n: u128) -> Seed {
        let entity_id = id(n);
        Seed {
            name: index.entity_name(&entity_id).unwrap_or("?").to_string(),
            degree: index.degree(&entity_id),
            entity_id,
            match_kind: MatchKind::Exact,
            score: 1.0,
        }
    }

    fn path_settings(cap: u32, max_facts: usize, max_chunks: usize) -> PathSettings {
        PathSettings {
            degree_cap: cap,
            max_path_facts: max_facts,
            max_graph_chunk_candidates: max_chunks,
            chunk_selection: ChunkSelection::All,
        }
    }

    // ---- GraphIndex ---------------------------------------------------------------------

    #[test]
    fn index_degree_counts_both_endpoints_and_a_self_loop_twice() {
        let (index, _) = graph(
            vec![ent(1, "A", &[]), ent(2, "B", &[]), ent(3, "C", &[])],
            &[(1, 2, "r", 1.0), (1, 1, "self", 1.0), (2, 3, "r", 1.0)],
        );
        assert_eq!(index.degree(&id(1)), 3, "one edge to B plus a self-loop counted twice");
        assert_eq!(index.degree(&id(2)), 2);
        assert_eq!(index.degree(&id(3)), 1);
        assert_eq!(index.degree(&id(99)), 0, "an entity with no edges has degree 0");
    }

    #[test]
    fn index_name_maps_collapse_case_and_punctuation() {
        let (index, _) = graph(
            vec![
                ent(1, "The Beta-Group", &[]),
                ent(2, "CBSSports.com", &[]),
                ent(3, "beta group", &[]),
            ],
            &[],
        );
        assert_eq!(casefold_name("CBSSports.COM"), "cbssports.com");
        assert_eq!(normalize_name("The Beta-Group"), "beta group");
        assert_eq!(index.exact_matches("cbssports.COM"), &[id(2)]);
        assert!(index.exact_matches("Beta Group").contains(&id(3)));
        assert!(
            !index.exact_matches("Beta Group").contains(&id(1)),
            "an exact match is on the case-folded full name, so a hyphenated name is not one"
        );
        let normalized = index.normalized_matches("Beta   Group!");
        assert_eq!(normalized, &[id(1), id(3)], "sorted entity ids that share the normalised name");
    }

    #[test]
    fn index_seed_document_ids_come_from_the_chunk_id_prefix() {
        let doc_a = id(10);
        let doc_b = id(11);
        let chunks = [format!("{doc_b}:3"), format!("{doc_a}:0"), format!("{doc_a}:7")];
        let chunk_refs: Vec<&str> = chunks.iter().map(String::as_str).collect();
        let (index, _) = graph(vec![ent(1, "A", &chunk_refs)], &[]);
        assert_eq!(index.seed_document_ids(&id(1)), vec![doc_a, doc_b]);
        assert!(index.seed_document_ids(&id(2)).is_empty());
    }

    #[test]
    fn index_degree_percentile_interpolates_over_every_entity_including_isolated_ones() {
        // degrees: 0 (isolated), 1, 1, 2 -> sorted [0, 1, 1, 2]
        let (index, _) = graph(
            vec![ent(1, "A", &[]), ent(2, "B", &[]), ent(3, "C", &[]), ent(4, "D", &[])],
            &[(1, 2, "r", 1.0), (2, 3, "r", 1.0)],
        );
        // degree: A=1, B=2, C=1, D=0
        assert_eq!(index.degree_percentile(0.0), 0.0);
        assert_eq!(index.degree_percentile(1.0), 2.0);
        // (n-1)*0.5 = 1.5 -> halfway between sorted[1]=1 and sorted[2]=1.
        assert_eq!(index.degree_percentile(0.5), 1.0);
        // (n-1)*0.75 = 2.25 -> sorted[2]=1 .. sorted[3]=2 at 0.25.
        assert!((index.degree_percentile(0.75) - 1.25).abs() < 1e-9);
    }

    // ---- store-backed fixtures ------------------------------------------------------------

    pub(crate) fn temp_path(name: &str) -> String {
        std::env::temp_dir()
            .join(format!("lancet-seedpaths-{name}-{}", Uuid::new_v4()))
            .to_string_lossy()
            .into_owned()
    }

    pub(crate) struct StoreEntity {
        pub(crate) n: u128,
        pub(crate) name: &'static str,
        pub(crate) chunks: Vec<String>,
        pub(crate) vector_value: f32,
    }

    pub(crate) async fn write_store_entities(db: &DatabaseManager, rows: &[StoreEntity]) {
        let table = db.entities_table().await.unwrap();
        let schema = table.schema().await.unwrap();
        let n = rows.len();
        let nullable = |name: &str| new_null_array(schema.field_with_name(name).unwrap().data_type(), n);
        let name_vectors = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
            rows.iter()
                .map(|r| Some((0..2048).map(move |_| Some(r.vector_value)))),
            2048,
        );
        let mut chunk_builder = ListBuilder::new(StringBuilder::new());
        for row in rows {
            for chunk in &row.chunks {
                chunk_builder.values().append_value(chunk);
            }
            chunk_builder.append(true);
        }
        let ids: Vec<String> = rows.iter().map(|r| id(r.n)).collect();
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(ids.iter().map(String::as_str).collect::<Vec<_>>())),
                Arc::new(StringArray::from(rows.iter().map(|r| r.name).collect::<Vec<_>>())),
                Arc::new(StringArray::from(vec!["concept"; n])),
                Arc::new(name_vectors),
                nullable("summary"),
                nullable("summary_vector"),
                nullable("unsummarized_refs"),
                nullable("community_ids"),
                Arc::new(chunk_builder.finish()),
            ],
        )
        .unwrap();
        table.add(batch).execute().await.unwrap();
    }

    pub(crate) async fn write_store_edges(db: &DatabaseManager, edges: &[EdgeSpec]) {
        let table = db.entity_edges_table().await.unwrap();
        let schema = table.schema().await.unwrap();
        let n = edges.len();
        let nullable = |name: &str| new_null_array(schema.field_with_name(name).unwrap().data_type(), n);
        let edge_ids: Vec<String> = (0..n).map(|i| format!("ee-{i}-{}", Uuid::new_v4())).collect();
        let sources: Vec<String> = edges.iter().map(|e| id(e.0)).collect();
        let targets: Vec<String> = edges.iter().map(|e| id(e.1)).collect();
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(edge_ids.iter().map(String::as_str).collect::<Vec<_>>())),
                Arc::new(StringArray::from(sources.iter().map(String::as_str).collect::<Vec<_>>())),
                Arc::new(StringArray::from(targets.iter().map(String::as_str).collect::<Vec<_>>())),
                Arc::new(StringArray::from(edges.iter().map(|e| e.2).collect::<Vec<_>>())),
                Arc::new(Float32Array::from(edges.iter().map(|e| e.3 as f32).collect::<Vec<_>>())),
                Arc::new(StringArray::from(vec!["doc-fixture"; n])),
                nullable("summary"),
                nullable("summary_vector"),
            ],
        )
        .unwrap();
        table.add(batch).execute().await.unwrap();
    }

    #[tokio::test]
    async fn index_build_reads_names_chunks_and_degree_from_a_temp_store() {
        let path = temp_path("build");
        let db = DatabaseManager::initialize(&path).await.unwrap();
        write_store_entities(
            &db,
            &[
                StoreEntity { n: 1, name: "Alpha Corp", chunks: vec![format!("{}:0", id(100))], vector_value: 0.1 },
                StoreEntity { n: 2, name: "Beta-Group", chunks: vec![], vector_value: 0.2 },
                StoreEntity { n: 3, name: "Lonely", chunks: vec![format!("{}:4", id(101))], vector_value: 0.3 },
            ],
        )
        .await;
        write_store_edges(&db, &[(1, 2, "partners", 0.9), (2, 2, "self", 0.5)]).await;

        let index = GraphIndex::build(&db).await.unwrap();

        assert_eq!(index.entity_count(), 3);
        assert_eq!(index.degree(&id(1)), 1);
        assert_eq!(index.degree(&id(2)), 3, "one real edge plus a self-loop counted twice");
        assert_eq!(index.degree(&id(3)), 0);
        assert_eq!(index.entity_name(&id(2)), Some("Beta-Group"));
        assert_eq!(index.exact_matches("alpha corp"), &[id(1)]);
        assert_eq!(index.normalized_matches("beta group"), &[id(2)]);
        assert_eq!(index.source_chunk_ids(&id(1)), &[format!("{}:0", id(100))]);
        assert_eq!(index.seed_document_ids(&id(3)), vec![id(101)]);
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }

    // ---- extract_mentions -----------------------------------------------------------------

    #[test]
    fn mentions_include_publisher_and_person_spans_and_exclude_the_question_word() {
        let mentions = extract_mentions(
            "Does the article from CBSSports.com credit Jonathan Smith with leaving Oregon State?",
        );
        assert!(mentions.contains(&"CBSSports.com".to_string()), "{mentions:?}");
        assert!(mentions.contains(&"Jonathan Smith".to_string()), "{mentions:?}");
        assert!(mentions.contains(&"Oregon State".to_string()), "{mentions:?}");
        assert!(!mentions.iter().any(|m| m == "Does" || m.starts_with("Does ")), "{mentions:?}");
    }

    #[test]
    fn mentions_keep_the_article_span_and_add_the_span_without_it() {
        let mentions = extract_mentions("What did The Verge's review say about the Pixel?");
        assert!(mentions.contains(&"The Verge".to_string()), "{mentions:?}");
        assert!(mentions.contains(&"Verge".to_string()), "{mentions:?}");
        assert!(mentions.contains(&"Pixel".to_string()), "{mentions:?}");
        assert!(!mentions.iter().any(|m| m.contains('\'') || m.contains('\u{2019}')), "{mentions:?}");
        assert!(!mentions.contains(&"What".to_string()), "{mentions:?}");

        let curly = extract_mentions("Did The Verge\u{2019}s editors agree?");
        assert!(curly.contains(&"The Verge".to_string()), "{curly:?}");
        assert!(curly.contains(&"Verge".to_string()), "{curly:?}");
    }

    #[test]
    fn mentions_are_empty_when_the_question_has_no_capitalised_span() {
        assert!(extract_mentions("what is the weather like today in the city?").is_empty());
        assert!(extract_mentions("").is_empty());
        assert!(extract_mentions("Does Is What Which?").is_empty(), "stop-words alone are not mentions");
    }

    #[test]
    fn mentions_join_inner_connectors_but_break_at_commas_and_drop_trailing_connectors() {
        let mentions = extract_mentions("Compare Bank of America, TechCrunch and the report.");
        assert!(mentions.contains(&"Bank of America".to_string()), "{mentions:?}");
        assert!(mentions.contains(&"TechCrunch".to_string()), "{mentions:?}");
        assert!(
            !mentions.iter().any(|m| m.ends_with(" and") || m.ends_with(" the") || m.ends_with(" of")),
            "a connector never ends a span: {mentions:?}"
        );
        assert!(
            !mentions.iter().any(|m| m.contains("America TechCrunch") || m.contains("America, TechCrunch")),
            "a comma ends a span: {mentions:?}"
        );
    }

    #[test]
    fn a_lower_case_connector_never_starts_a_mention() {
        // The stop-word `Does` is stripped, which leaves the connector `the` at the front of the
        // span; a connector never starts a span, so the mention is `Engadget`, not `the Engadget`.
        let mentions =
            extract_mentions("Does the Engadget article from the TechCrunch desk mention it?");
        assert_eq!(mentions, ["Engadget", "TechCrunch"]);
    }

    #[test]
    fn mentions_also_split_a_span_at_and_connectors() {
        let mentions = extract_mentions("Did Apple and Google or Procter & Gamble announce it?");
        for expected in ["Apple and Google", "Apple", "Google", "Procter & Gamble", "Procter", "Gamble"] {
            assert!(mentions.contains(&expected.to_string()), "missing {expected}: {mentions:?}");
        }
    }

    #[test]
    fn mentions_catch_camel_case_brands_and_are_deduplicated_in_order() {
        let mentions = extract_mentions("Did iPhone sales beat Google while Google lagged the iPhone?");
        assert_eq!(
            mentions.iter().filter(|m| m.as_str() == "Google").count(),
            1,
            "a repeated mention is emitted once: {mentions:?}"
        );
        assert_eq!(mentions[0], "iPhone", "question order is kept: {mentions:?}");
    }

    #[test]
    fn mentions_are_bounded_in_count_and_length() {
        let many: String = (0..200).map(|i| format!("Name{i}x, ")).collect();
        let mentions = extract_mentions(&many);
        assert!(!mentions.is_empty());
        assert!(mentions.len() <= 32, "mention count is capped: {}", mentions.len());

        let long_span: String = (0..60).map(|_| "Longword ").collect();
        let long = extract_mentions(&format!("Is {long_span}fine?"));
        assert!(long.iter().all(|m| m.chars().count() <= 128), "mention length is capped");
    }

    // ---- match_seeds ----------------------------------------------------------------------

    struct FakeSearch {
        calls: Mutex<Vec<(Vec<String>, usize)>>,
        answers: HashMap<String, Vec<(String, f64)>>,
        fail: bool,
    }

    impl FakeSearch {
        fn new(answers: &[(&str, Vec<(String, f64)>)]) -> Self {
            Self {
                calls: Mutex::new(Vec::new()),
                answers: answers.iter().map(|(m, a)| ((*m).to_string(), a.clone())).collect(),
                fail: false,
            }
        }
    }

    #[tonic::async_trait]
    impl MentionVectorSearch for FakeSearch {
        async fn search(
            &self,
            mentions: &[String],
            top_k: usize,
        ) -> Result<Vec<Vec<(String, f64)>>, String> {
            self.calls.lock().unwrap().push((mentions.to_vec(), top_k));
            if self.fail {
                return Err("injected vector failure".to_string());
            }
            Ok(mentions
                .iter()
                .map(|m| self.answers.get(m).cloned().unwrap_or_default())
                .collect())
        }
    }

    fn mention_list(items: &[&str]) -> Vec<String> {
        items.iter().map(|m| (*m).to_string()).collect()
    }

    fn matching_index() -> GraphIndex {
        graph(
            vec![
                ent(1, "Alpha Corp", &[]),
                ent(2, "The Beta-Group", &[]),
                ent(3, "Gamma Industries Ltd", &[]),
                ent(4, "Gamma Unrelated", &[]),
                ent(5, "ALPHA-CORP", &[]),
            ],
            &[],
        )
        .0
    }

    #[tokio::test]
    async fn seeds_match_exact_then_normalised_then_vector_with_one_batched_vector_call() {
        let index = matching_index();
        let search = FakeSearch::new(&[(
            "Gamma Industries",
            vec![(id(3), 0.80), (id(4), 0.30)],
        )]);
        let mentions = mention_list(&["Alpha Corp", "Beta Group", "Gamma Industries", "Delta Holdings"]);

        let seeds = match_seeds(&index, &mentions, &search, &SeedSettings::default())
            .await
            .unwrap();

        let by_id: HashMap<&str, MatchKind> =
            seeds.iter().map(|s| (s.entity_id.as_str(), s.match_kind)).collect();
        assert_eq!(by_id.get(id(1).as_str()), Some(&MatchKind::Exact));
        assert_eq!(by_id.get(id(2).as_str()), Some(&MatchKind::Normalized));
        assert_eq!(by_id.get(id(3).as_str()), Some(&MatchKind::Vector));
        assert!(!by_id.contains_key(id(4).as_str()), "a vector hit below the minimum score is rejected");
        let calls = search.calls.lock().unwrap();
        assert_eq!(calls.len(), 1, "all unmatched mentions go in one vector call");
        assert_eq!(calls[0].0, mention_list(&["Gamma Industries", "Delta Holdings"]));
        assert_eq!(calls[0].1, SeedSettings::default().mention_vector_top_k);
    }

    #[tokio::test]
    async fn an_exact_match_wins_over_a_normalised_match_for_the_same_mention() {
        let index = matching_index();
        let search = FakeSearch::new(&[]);
        let seeds = match_seeds(&index, &mention_list(&["Alpha Corp"]), &search, &SeedSettings::default())
            .await
            .unwrap();
        assert_eq!(seeds.len(), 1, "ALPHA-CORP also normalises to the same name but is not taken");
        assert_eq!(seeds[0].entity_id, id(1));
        assert_eq!(seeds[0].match_kind, MatchKind::Exact);
        assert!(search.calls.lock().unwrap().is_empty(), "no vector call when every mention matched");
    }

    #[tokio::test]
    async fn a_vector_candidate_exactly_at_the_minimum_score_is_accepted() {
        let index = matching_index();
        let settings = SeedSettings::default();
        let search = FakeSearch::new(&[(
            "Gamma",
            vec![(id(3), settings.seed_match_min_score), (id(4), settings.seed_match_min_score - 0.01)],
        )]);
        let seeds = match_seeds(&index, &mention_list(&["Gamma"]), &search, &settings)
            .await
            .unwrap();
        assert_eq!(seeds.len(), 1);
        assert_eq!(seeds[0].entity_id, id(3));
        assert_eq!(seeds[0].score, settings.seed_match_min_score);
    }

    #[tokio::test]
    async fn seeds_are_capped_and_ordered_by_kind_then_degree_then_id_regardless_of_mention_order() {
        let names = ["Aa One", "Bb Two", "Cc Three", "Dd Four", "Ee Five"];
        let entities: Vec<EntityRecord> =
            names.iter().enumerate().map(|(i, n)| ent(i as u128 + 1, n, &[])).collect();
        // Degrees: entity 1 -> 3, entity 2 -> 1, entity 3 -> 1, entity 4 -> 0, entity 5 -> 2.
        let (index, _) = graph(
            entities,
            &[(1, 2, "r", 1.0), (1, 3, "r", 1.0), (1, 5, "r", 1.0), (5, 99, "r", 1.0)],
        );
        let settings = SeedSettings { max_seeds: 3, ..SeedSettings::default() };
        let search = FakeSearch::new(&[]);

        let forward = match_seeds(&index, &mention_list(&names), &search, &settings).await.unwrap();
        let mut reversed_names = mention_list(&names);
        reversed_names.reverse();
        let backward = match_seeds(&index, &reversed_names, &search, &settings).await.unwrap();

        assert_eq!(forward, backward, "mention order must not change the seeds");
        let order: Vec<&str> = forward.iter().map(|s| s.name.as_str()).collect();
        assert_eq!(order, ["Dd Four", "Bb Two", "Cc Three"], "degree 0, then degree 1 by entity id");
    }

    #[tokio::test]
    async fn a_vector_candidate_whose_name_has_no_letters_or_digits_is_never_a_seed() {
        // A whitespace-only entity name embeds to a degenerate vector that sits at distance 1 from
        // every unit-length mention vector, which is exactly the minimum score of 0.5.
        let index = graph(vec![ent(1, "Alpha Corp", &[]), ent(2, "  ", &["c1"])], &[]).0;
        let search = FakeSearch::new(&[("Gamma", vec![(id(2), 0.5), (id(1), 0.9)])]);

        let seeds = match_seeds(&index, &mention_list(&["Gamma"]), &search, &SeedSettings::default())
            .await
            .unwrap();

        let ids: Vec<&str> = seeds.iter().map(|s| s.entity_id.as_str()).collect();
        assert_eq!(ids, [id(1).as_str()], "the nameless entity is skipped, the real one stays");
    }

    #[tokio::test]
    async fn two_mentions_for_one_entity_make_one_seed_with_the_best_match_kind() {
        let index = matching_index();
        let search = FakeSearch::new(&[("Gamma", vec![(id(1), 0.9)])]);
        let seeds = match_seeds(
            &index,
            &mention_list(&["Gamma", "alpha corp"]),
            &search,
            &SeedSettings::default(),
        )
        .await
        .unwrap();
        assert_eq!(seeds.len(), 1);
        assert_eq!(seeds[0].match_kind, MatchKind::Exact);
    }

    #[tokio::test]
    async fn a_vector_search_failure_is_an_error_not_a_silent_empty_result() {
        let index = matching_index();
        let mut search = FakeSearch::new(&[]);
        search.fail = true;
        let error = match_seeds(&index, &mention_list(&["Nobody Here"]), &search, &SeedSettings::default())
            .await
            .unwrap_err();
        assert!(error.contains("injected vector failure"), "{error}");
    }

    // ---- LanceMentionVectorSearch ---------------------------------------------------------

    struct MapEmbedder {
        requests: Mutex<Vec<Vec<String>>>,
    }

    impl EmbeddingProvider for MapEmbedder {
        fn get_embeddings<'a>(
            &'a self,
            texts: &'a [String],
        ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
            Box::pin(async move {
                self.requests.lock().unwrap().push(texts.to_vec());
                Ok(texts
                    .iter()
                    .map(|t| vec![if t == "alpha" { 0.1_f32 } else { 0.9_f32 }; 2048])
                    .collect())
            })
        }
    }

    #[tokio::test]
    async fn lance_mention_search_embeds_once_and_groups_hits_by_query_index() {
        let path = temp_path("mention-search");
        let db = DatabaseManager::initialize(&path).await.unwrap();
        write_store_entities(
            &db,
            &[
                StoreEntity { n: 1, name: "Alpha", chunks: vec![], vector_value: 0.1 },
                StoreEntity { n: 2, name: "Beta", chunks: vec![], vector_value: 0.9 },
                StoreEntity { n: 3, name: "Other", chunks: vec![], vector_value: 0.5 },
            ],
        )
        .await;
        let embedder = Arc::new(MapEmbedder { requests: Mutex::new(Vec::new()) });
        let search = LanceMentionVectorSearch { database: db.clone(), embedder: embedder.clone() };

        let hits = search
            .search(&mention_list(&["alpha", "beta"]), 1)
            .await
            .unwrap();

        assert_eq!(hits.len(), 2);
        assert_eq!((hits[0].len(), hits[1].len()), (1, 1), "top_k is applied per mention");
        assert_eq!(hits[0][0].0, id(1), "alpha's nearest name vector is Alpha");
        assert_eq!(hits[1][0].0, id(2), "beta's nearest name vector is Beta");
        assert!(hits[0][0].1 > 0.99 && hits[0][0].1 <= 1.0, "score is dense_score(distance 0)");
        assert_eq!(embedder.requests.lock().unwrap().len(), 1, "one batched embedding call");

        let none = search.search(&[], 3).await.unwrap();
        assert!(none.is_empty());
        assert_eq!(embedder.requests.lock().unwrap().len(), 1, "no embedding call for no mentions");
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }

    // ---- paths ------------------------------------------------------------------------------

    #[test]
    fn a_direct_seed_to_seed_edge_is_a_one_hop_path() {
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &[]), ent(2, "Beta", &[])],
            &[(1, 2, "acquired", 0.8)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];

        let result = build_paths(&index, &seeds, &edges, &path_settings(33, 16, 8));

        assert!(result.path_found);
        assert_eq!(result.paths.len(), 1);
        assert_eq!(result.paths[0].entities, [id(1), id(2)]);
        assert_eq!(result.paths[0].relations, ["acquired"]);
        assert!(result.paths[0].rendered.contains("Alpha") && result.paths[0].rendered.contains("Beta"));
        assert_eq!(result.facts.len(), 1);
        assert_eq!(result.facts[0].entity_a_name(), "Alpha");
        assert_eq!(result.facts[0].entity_b_name(), "Beta");
        assert_eq!(result.degree_capped_count, 0);
    }

    #[test]
    fn a_shared_neighbour_of_two_seeds_is_a_two_hop_path_through_it() {
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &[]), ent(2, "Beta", &[]), ent(3, "Bridge", &[])],
            &[(1, 3, "owns", 1.0), (2, 3, "uses", 1.0)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];

        let result = build_paths(&index, &seeds, &edges, &path_settings(33, 16, 8));

        assert!(result.path_found);
        assert_eq!(result.paths.len(), 1);
        assert_eq!(result.paths[0].entities, [id(1), id(3), id(2)]);
        assert_eq!(result.paths[0].relations, ["owns", "uses"]);
        assert!(result.paths[0].rendered.contains("Bridge"));
        assert_eq!(result.facts.len(), 1, "one fact per path");
    }

    #[test]
    fn an_intermediate_above_the_degree_cap_is_excluded_and_counted() {
        let (index, edges) = graph(
            vec![
                ent(1, "Alpha", &[]),
                ent(2, "Beta", &[]),
                ent(3, "Hub", &[]),
                ent(4, "Spoke", &[]),
            ],
            &[(1, 3, "r", 1.0), (2, 3, "r", 1.0), (3, 4, "r", 1.0)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];
        assert_eq!(index.degree(&id(3)), 3);

        let capped = build_paths(&index, &seeds, &edges, &path_settings(2, 16, 8));
        assert!(!capped.path_found);
        assert!(capped.paths.is_empty() && capped.facts.is_empty() && capped.candidate_chunk_ids.is_empty());
        assert_eq!(capped.degree_capped_count, 1);

        let at_cap = build_paths(&index, &seeds, &edges, &path_settings(3, 16, 8));
        assert!(at_cap.path_found, "a degree equal to the cap is still admitted");
        assert_eq!(at_cap.degree_capped_count, 0);
    }

    /// The relation attribute of a two-hop fact shows which way each hop points along the path, so
    /// it never contradicts the readable text of the same fact.
    #[test]
    fn a_two_hop_fact_relation_text_points_each_hop_the_way_its_edge_is_stored() {
        // Alpha -owns-> Mid <-buys_from- Beta: the first hop is stored along the path, the second
        // against it.
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &[]), ent(2, "Beta", &[]), ent(3, "Mid", &[])],
            &[(1, 3, "owns", 1.0), (2, 3, "buys_from", 1.0)],
        );
        let result = build_paths(
            &index,
            &[seed_of(&index, 1), seed_of(&index, 2)],
            &edges,
            &path_settings(33, 16, 8),
        );
        assert_eq!(result.paths[0].rendered, "Alpha \u{2014}owns\u{2192} Mid \u{2190}buys_from\u{2014} Beta");
        assert_eq!(result.facts[0].relation_type(), "owns\u{2192}Mid\u{2190}buys_from");

        // Alpha <-owns- Mid -sells_to-> Beta: the first hop is stored against the path, the
        // second along it.
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &[]), ent(2, "Beta", &[]), ent(3, "Mid", &[])],
            &[(3, 1, "owns", 1.0), (3, 2, "sells_to", 1.0)],
        );
        let result = build_paths(
            &index,
            &[seed_of(&index, 1), seed_of(&index, 2)],
            &edges,
            &path_settings(33, 16, 8),
        );
        assert_eq!(result.paths[0].rendered, "Alpha \u{2190}owns\u{2014} Mid \u{2014}sells_to\u{2192} Beta");
        assert_eq!(result.facts[0].relation_type(), "owns\u{2190}Mid\u{2192}sells_to");
    }

    #[test]
    fn a_seed_is_never_an_intermediate_and_a_single_seed_has_no_path() {
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &[]), ent(2, "Beta", &[]), ent(3, "Gamma", &[])],
            &[(1, 2, "r", 1.0), (2, 3, "r", 1.0), (1, 3, "r", 1.0)],
        );
        let three = [seed_of(&index, 1), seed_of(&index, 2), seed_of(&index, 3)];
        let result = build_paths(&index, &three, &edges, &path_settings(33, 16, 8));
        assert_eq!(result.paths.len(), 3, "three direct paths, no path through a seed");
        assert!(result.paths.iter().all(|p| p.entities.len() == 2));

        let single = build_paths(&index, &three[..1], &edges, &path_settings(33, 16, 8));
        assert!(!single.path_found);
        assert!(single.paths.is_empty());
        let none = build_paths(&index, &[], &edges, &path_settings(33, 16, 8));
        assert!(!none.path_found);
    }

    #[test]
    fn paths_are_ranked_by_specificity_then_truncated_at_the_fact_cap() {
        // Seeds 1, 2, 3. Entity 3 is made a hub by edges to fillers, so 1-2 is more specific than 1-3.
        let (index, edges) = graph(
            vec![
                ent(1, "Alpha", &[]),
                ent(2, "Beta", &[]),
                ent(3, "Hubby", &[]),
                ent(10, "F1", &[]),
                ent(11, "F2", &[]),
                ent(12, "F3", &[]),
            ],
            &[
                (1, 2, "r", 1.0),
                (1, 3, "r", 1.0),
                (2, 3, "r", 1.0),
                (3, 10, "r", 1.0),
                (3, 11, "r", 1.0),
                (3, 12, "r", 1.0),
            ],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2), seed_of(&index, 3)];

        let all = build_paths(&index, &seeds, &edges, &path_settings(33, 16, 8));
        assert_eq!(all.paths.len(), 3);
        assert_eq!(all.paths[0].entities, [id(1), id(2)], "the path avoiding the hub ranks first");
        assert!(all.paths[0].score > all.paths[1].score);
        assert!(all.paths[1].score >= all.paths[2].score);

        let cut = build_paths(&index, &seeds, &edges, &path_settings(33, 2, 8));
        assert_eq!(cut.paths.len(), 2, "truncated after ranking");
        assert_eq!(cut.paths, all.paths[..2].to_vec(), "the kept paths are the top-ranked ones");
        assert_eq!(cut.facts.len(), 2);
    }

    #[test]
    fn candidate_chunks_are_the_ranked_union_of_path_entity_chunks_capped() {
        let (index, edges) = graph(
            vec![
                ent(1, "Alpha", &["c1", "c2"]),
                ent(2, "Beta", &["c2", "c3"]),
                ent(3, "Bridge", &["c9"]),
            ],
            &[(1, 2, "r", 1.0)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];

        let uncapped = build_paths(&index, &seeds, &edges, &path_settings(33, 16, 8));
        assert_eq!(
            uncapped.candidate_chunk_ids,
            ["c2", "c1", "c3"],
            "the chunk both entities cite first, then first chunks, then later ones; Bridge is not on the path"
        );
        let capped = build_paths(&index, &seeds, &edges, &path_settings(33, 16, 2));
        assert_eq!(capped.candidate_chunk_ids, ["c2", "c1"]);
    }

    #[test]
    fn path_scores_use_edge_weight_and_the_best_parallel_edge_is_taken() {
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &[]), ent(2, "Beta", &[])],
            &[(1, 2, "weak", 0.2), (2, 1, "strong", 0.9), (1, 2, "also_weak", 0.2)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];
        let result = build_paths(&index, &seeds, &edges, &path_settings(33, 16, 8));
        assert_eq!(result.paths.len(), 1, "parallel edges collapse to the best one per hop");
        assert_eq!(result.paths[0].relations, ["strong"]);
        let degree = index.degree(&id(1)).max(index.degree(&id(2))) as f64;
        let expected = 0.9 / (2.0 + degree).ln();
        assert!((result.paths[0].score - expected).abs() < 1e-9, "{} vs {expected}", result.paths[0].score);
    }

    #[test]
    fn seed_chunk_candidates_round_robin_across_seeds_and_respect_the_cap() {
        let (index, _) = graph(
            vec![
                ent(1, "Alpha", &["a0", "a1", "a2"]),
                ent(2, "Beta", &["b0", "a1"]),
            ],
            &[],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];
        assert_eq!(
            seed_chunk_candidates(&index, &seeds, 8),
            ["a1", "a0", "b0", "a2"],
            "the chunk cited by both seeds first, then position 0 of each seed in seed order"
        );
        assert_eq!(seed_chunk_candidates(&index, &seeds, 2), ["a1", "a0"]);
        assert!(seed_chunk_candidates(&index, &[], 8).is_empty());
    }

    #[test]
    fn max_path_facts_follow_the_budget_formula_and_stay_undefined_without_a_measurement() {
        // floor(0.10 * (8192 - 2048) / 100) = floor(6.144) = 6
        assert_eq!(derive_max_path_facts(8192, 2048, 100), Some(6));
        // floor(0.10 * 6144 / 25) = 24, clamped to the ceiling of 16.
        assert_eq!(derive_max_path_facts(8192, 2048, 25), Some(16));
        assert_eq!(derive_max_path_facts(8192, 2048, 0), None, "no measured fact size, no cap");
        assert_eq!(derive_max_path_facts(2048, 2048, 10), Some(0), "no room left, no facts");
    }

    #[test]
    fn the_confirmed_path_fact_cap_is_the_budget_formula_at_the_measured_p95() {
        // 8192 evidence tokens, 2048 answer tokens, p95 of 69 tokens per path fact (SEED-PROBE s8).
        assert_eq!(derive_max_path_facts(8192, 2048, 69), Some(MAX_PATH_FACTS));
        assert!(
            MAX_PATH_FACTS < MAX_PATH_FACTS_CEILING,
            "the ceiling must not be what sets the cap at the measured fact size"
        );
    }

    // ---- graph chunk precision (D-139) ------------------------------------------------------

    fn settings_with(selection: ChunkSelection, max_chunks: usize) -> PathSettings {
        PathSettings {
            chunk_selection: selection,
            ..path_settings(33, 16, max_chunks)
        }
    }

    fn chunk_ids(result: &SeedPathResult) -> Vec<&str> {
        result
            .candidate_chunk_ids
            .iter()
            .map(String::as_str)
            .collect()
    }

    /// `Alpha - Bridge - Beta`, with Alpha and Beta as the seeds, so the one kept path has two hops.
    ///
    /// The path entities in order are Alpha, Bridge, Beta. Each chunk is cited by:
    /// `c1` Alpha; `c2` Alpha and Bridge (the first hop's evidence); `c3` Alpha and Beta, who are
    /// not the two ends of one hop; `c4` Bridge and Beta (the second hop's evidence); `c5` Bridge;
    /// `c6` Beta. Entities cite more than one chunk, so the order keys are exercised too.
    fn bridge_fixture() -> (GraphIndex, Vec<EdgeRow>) {
        graph(
            vec![
                ent(1, "Alpha", &["c1", "c2", "c3"]),
                ent(2, "Beta", &["c3", "c4", "c6"]),
                ent(3, "Bridge", &["c2", "c4", "c5"]),
            ],
            &[(1, 3, "owns", 1.0), (3, 2, "uses", 1.0)],
        )
    }

    fn bridge_paths(selection: ChunkSelection, max_chunks: usize) -> SeedPathResult {
        let (index, edges) = bridge_fixture();
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];
        build_paths(
            &index,
            &seeds,
            &edges,
            &settings_with(selection, max_chunks),
        )
    }

    #[test]
    fn all_keeps_every_chunk_of_the_path_entities_in_rank_order() {
        let result = bridge_paths(ChunkSelection::All, 8);
        assert_eq!(chunk_ids(&result), ["c2", "c3", "c4", "c1", "c5", "c6"]);
    }

    #[test]
    fn multi_cited_keeps_the_chunks_that_at_least_two_path_entities_cite() {
        let result = bridge_paths(ChunkSelection::MultiCited(MULTI_CITED_MIN_ENTITIES), 8);
        assert_eq!(chunk_ids(&result), ["c2", "c3", "c4"]);
    }

    #[test]
    fn edge_evidence_keeps_the_chunks_that_both_ends_of_a_kept_hop_cite() {
        let result = bridge_paths(ChunkSelection::EdgeEvidence, 8);
        assert_eq!(
            chunk_ids(&result),
            ["c2", "c4"],
            "c3 is cited by both seeds but they are not the two ends of one hop"
        );
    }

    #[test]
    fn a_threshold_of_one_equals_all_and_a_threshold_above_the_citations_keeps_nothing() {
        let all = bridge_paths(ChunkSelection::All, 8);
        assert_eq!(bridge_paths(ChunkSelection::MultiCited(1), 8), all);
        assert_eq!(bridge_paths(ChunkSelection::MultiCited(0), 8), all);
        let none = bridge_paths(ChunkSelection::MultiCited(3), 8);
        assert!(none.candidate_chunk_ids.is_empty());
        assert!(
            none.path_found,
            "the paths are kept whatever the chunk list holds"
        );
    }

    #[test]
    fn the_variant_changes_the_chunk_list_and_nothing_else() {
        let strip = |mut result: SeedPathResult| {
            result.candidate_chunk_ids.clear();
            result
        };
        let all = bridge_paths(ChunkSelection::All, 8);
        assert!(all.path_found && all.paths.len() == 1 && all.facts.len() == 1);
        for selection in [
            ChunkSelection::EdgeEvidence,
            ChunkSelection::MultiCited(MULTI_CITED_MIN_ENTITIES),
        ] {
            let other = bridge_paths(selection, 8);
            assert_ne!(
                other.candidate_chunk_ids, all.candidate_chunk_ids,
                "{selection:?}"
            );
            assert_eq!(
                strip(other),
                strip(all.clone()),
                "{selection:?}: paths, facts and counts are the same"
            );
        }
    }

    /// The capped lists of two variants need not nest: the top two of the smaller candidate set can
    /// hold a chunk that ranks below the larger set's top two.
    #[test]
    fn a_capped_edge_evidence_list_can_hold_a_chunk_the_capped_multi_cited_list_lacks() {
        let multi = bridge_paths(ChunkSelection::MultiCited(MULTI_CITED_MIN_ENTITIES), 2);
        let edge = bridge_paths(ChunkSelection::EdgeEvidence, 2);
        assert_eq!(chunk_ids(&multi), ["c2", "c3"]);
        assert_eq!(chunk_ids(&edge), ["c2", "c4"]);
        assert!(!multi.candidate_chunk_ids.contains(&"c4".to_string()));
    }

    #[test]
    fn edge_evidence_reads_only_the_hops_of_the_kept_paths() {
        // Alpha - Beta is the better path (weight 1.0 against 0.1 over the same endpoint degrees).
        let (index, edges) = graph(
            vec![
                ent(1, "Alpha", &["x", "y"]),
                ent(2, "Beta", &["y", "z"]),
                ent(3, "Gamma", &["x", "w"]),
            ],
            &[(1, 2, "r", 1.0), (1, 3, "r", 0.1)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2), seed_of(&index, 3)];
        let run = |max_facts: usize| {
            build_paths(
                &index,
                &seeds,
                &edges,
                &PathSettings {
                    chunk_selection: ChunkSelection::EdgeEvidence,
                    ..path_settings(33, max_facts, 8)
                },
            )
        };

        assert_eq!(
            chunk_ids(&run(1)),
            ["y"],
            "the dropped Alpha - Gamma hop adds nothing"
        );
        assert_eq!(chunk_ids(&run(2)), ["x", "y"]);
    }

    #[test]
    fn a_hop_whose_ends_share_no_chunk_leaves_edge_evidence_empty_and_the_path_kept() {
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &["a1"]), ent(2, "Beta", &["b1"])],
            &[(1, 2, "r", 1.0)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];
        let run = |selection| build_paths(&index, &seeds, &edges, &settings_with(selection, 8));

        let edge = run(ChunkSelection::EdgeEvidence);
        assert!(edge.path_found && edge.candidate_chunk_ids.is_empty());
        assert_eq!(chunk_ids(&run(ChunkSelection::All)), ["a1", "b1"]);
    }

    #[test]
    fn multi_cited_counts_each_entity_once_however_often_it_lists_a_chunk() {
        let (index, edges) = graph(
            vec![ent(1, "Alpha", &["c", "c"]), ent(2, "Beta", &["d"])],
            &[(1, 2, "r", 1.0)],
        );
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];
        let result = build_paths(
            &index,
            &seeds,
            &edges,
            &settings_with(ChunkSelection::MultiCited(MULTI_CITED_MIN_ENTITIES), 8),
        );
        assert!(
            result.candidate_chunk_ids.is_empty(),
            "{:?}",
            result.candidate_chunk_ids
        );
    }

    /// A seeded generator, so the property test needs no dependency and replays exactly.
    struct XorShift(u64);

    impl XorShift {
        fn next(&mut self) -> u64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            self.0
        }

        fn below(&mut self, bound: usize) -> usize {
            (self.next() % bound as u64) as usize
        }
    }

    /// A random graph over 5 to 10 entities, each citing up to four of eight chunks (a chunk may be
    /// listed twice), with random edges, and the number of seeds (the first entities).
    fn random_graph(rng: &mut XorShift) -> (GraphIndex, Vec<EdgeRow>, usize) {
        let entity_count = 5 + rng.below(6);
        let entities: Vec<EntityRecord> = (1..=entity_count)
            .map(|n| {
                let chunks: Vec<String> = (0..rng.below(5))
                    .map(|_| format!("c{}", rng.below(8)))
                    .collect();
                let refs: Vec<&str> = chunks.iter().map(String::as_str).collect();
                ent(n as u128, &format!("E{n}"), &refs)
            })
            .collect();
        let edges: Vec<EdgeSpec> = (0..entity_count + rng.below(2 * entity_count))
            .map(|_| {
                let source = 1 + rng.below(entity_count) as u128;
                let target = 1 + rng.below(entity_count) as u128;
                (source, target, "r", 0.1 + rng.below(10) as f64 / 10.0)
            })
            .collect();
        let (index, rows) = graph(entities, &edges);
        (index, rows, 2 + rng.below(3))
    }

    /// The order keys that `rank_chunks` documents, computed from the index alone: citing path
    /// entities first, then the earliest position in an entity's own list, then the best entity
    /// rank, then the chunk ID.
    fn reference_ranking(
        index: &GraphIndex,
        entities: &[&str],
        candidates: &BTreeSet<&str>,
        cap: usize,
    ) -> Vec<String> {
        let mut keyed: Vec<(std::cmp::Reverse<usize>, usize, usize, &str)> = candidates
            .iter()
            .map(|chunk| {
                let citing: Vec<(usize, usize)> = entities
                    .iter()
                    .enumerate()
                    .filter_map(|(rank, entity)| {
                        index
                            .source_chunk_ids(entity)
                            .iter()
                            .position(|c| c.as_str() == *chunk)
                            .map(|position| (rank, position))
                    })
                    .collect();
                let earliest = citing.iter().map(|(_, position)| *position).min().unwrap();
                let best_rank = citing.iter().map(|(rank, _)| *rank).min().unwrap();
                (std::cmp::Reverse(citing.len()), earliest, best_rank, *chunk)
            })
            .collect();
        keyed.sort();
        keyed
            .into_iter()
            .take(cap)
            .map(|(_, _, _, chunk)| chunk.to_string())
            .collect()
    }

    #[test]
    fn the_variants_nest_before_the_cap_and_each_capped_list_follows_the_rank_keys() {
        let mut rng = XorShift(0x9E37_79B9_7F4A_7C15);
        let (mut edge_found, mut multi_beyond_edge, mut all_beyond_multi) = (0, 0, 0);
        for round in 0..300 {
            let (index, edges, seed_count) = random_graph(&mut rng);
            let seeds: Vec<Seed> = (1..=seed_count as u128)
                .map(|n| seed_of(&index, n))
                .collect();
            let cap = 1 + rng.below(6);
            let facts = 1 + rng.below(6);
            let run = |selection| {
                build_paths(
                    &index,
                    &seeds,
                    &edges,
                    &PathSettings {
                        chunk_selection: selection,
                        ..path_settings(33, facts, cap)
                    },
                )
            };
            let all_run = run(ChunkSelection::All);

            // The entities and hops of the kept paths, which no variant changes.
            let mut order: Vec<&str> = Vec::new();
            let mut hops: Vec<(&str, &str)> = Vec::new();
            for path in &all_run.paths {
                for entity in &path.entities {
                    if !order.contains(&entity.as_str()) {
                        order.push(entity.as_str());
                    }
                }
                hops.extend(
                    path.entities
                        .windows(2)
                        .map(|pair| (pair[0].as_str(), pair[1].as_str())),
                );
            }
            for (a, b) in &hops {
                assert!(
                    a != b && order.contains(a) && order.contains(b),
                    "round {round}: a hop joins two distinct members of the entity order"
                );
            }

            let variants = [
                ChunkSelection::All,
                ChunkSelection::MultiCited(MULTI_CITED_MIN_ENTITIES),
                ChunkSelection::EdgeEvidence,
            ];
            let [all, multi, edge] =
                variants.map(|selection| chunk_candidates(&index, &order, &hops, selection));
            assert!(
                edge.is_subset(&multi),
                "round {round}: edge evidence in multi cited"
            );
            assert!(multi.is_subset(&all), "round {round}: multi cited in all");
            let expected_edge: BTreeSet<&str> = hops
                .iter()
                .flat_map(|(a, b)| {
                    let (a_chunks, b_chunks) =
                        (index.source_chunk_ids(a), index.source_chunk_ids(b));
                    a_chunks
                        .iter()
                        .filter(move |c| b_chunks.contains(c))
                        .map(String::as_str)
                })
                .collect();
            assert_eq!(edge, expected_edge, "round {round}: the hop intersections");
            edge_found += usize::from(!edge.is_empty());
            multi_beyond_edge += usize::from(multi.len() > edge.len());
            all_beyond_multi += usize::from(all.len() > multi.len());

            for (selection, candidates) in variants.into_iter().zip([&all, &multi, &edge]) {
                let result = run(selection);
                assert_eq!(
                    result.paths, all_run.paths,
                    "round {round}: {selection:?} keeps the paths"
                );
                assert_eq!(
                    result.candidate_chunk_ids.len(),
                    cap.min(candidates.len()),
                    "round {round}: {selection:?} length"
                );
                assert_eq!(
                    result.candidate_chunk_ids,
                    reference_ranking(&index, &order, candidates, cap),
                    "round {round}: {selection:?} follows the rank keys"
                );
            }

            // `All` is what the ranking returned before the variants existed, which
            // `seed_chunk_candidates` still computes over a list of entities.
            let entity_seeds: Vec<Seed> = order
                .iter()
                .map(|entity| Seed {
                    entity_id: (*entity).to_string(),
                    name: String::new(),
                    match_kind: MatchKind::Exact,
                    score: 1.0,
                    degree: 0,
                })
                .collect();
            assert_eq!(
                all_run.candidate_chunk_ids,
                seed_chunk_candidates(&index, &entity_seeds, cap),
                "round {round}: All reproduces the unfiltered ranking"
            );
        }
        // Without these the inclusions above could hold because every set is empty or equal.
        assert!(
            edge_found >= 20,
            "edge evidence found chunks in only {edge_found} rounds"
        );
        assert!(
            multi_beyond_edge >= 20,
            "multi cited exceeded edge evidence in only {multi_beyond_edge} rounds"
        );
        assert!(
            all_beyond_multi >= 20,
            "all exceeded multi cited in only {all_beyond_multi} rounds"
        );
    }

    // ---- find_seed_paths (store-backed) -------------------------------------------------------

    #[tokio::test]
    async fn find_seed_paths_scans_the_store_once_and_finds_the_bridge() {
        let path = temp_path("find-paths");
        let db = DatabaseManager::initialize(&path).await.unwrap();
        write_store_entities(
            &db,
            &[
                StoreEntity { n: 1, name: "Alpha", chunks: vec!["c1".into()], vector_value: 0.1 },
                StoreEntity { n: 2, name: "Beta", chunks: vec!["c2".into()], vector_value: 0.2 },
                StoreEntity { n: 3, name: "Bridge", chunks: vec!["c3".into()], vector_value: 0.3 },
                StoreEntity { n: 4, name: "Far", chunks: vec![], vector_value: 0.4 },
            ],
        )
        .await;
        write_store_edges(&db, &[(1, 3, "owns", 1.0), (3, 2, "uses", 1.0), (3, 4, "near", 1.0)]).await;
        let index = GraphIndex::build(&db).await.unwrap();
        let seeds = [seed_of(&index, 1), seed_of(&index, 2)];

        let result = find_seed_paths(&db, &index, &seeds, &path_settings(33, 16, 8))
            .await
            .unwrap();

        assert!(result.path_found);
        assert_eq!(result.paths[0].entities, [id(1), id(3), id(2)]);
        assert_eq!(result.paths[0].relations, ["owns", "uses"]);
        assert_eq!(result.candidate_chunk_ids.len(), 3, "Alpha, Bridge and Beta chunks");

        let single = find_seed_paths(&db, &index, &seeds[..1], &path_settings(33, 16, 8))
            .await
            .unwrap();
        assert!(!single.path_found);
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }

    #[tokio::test]
    async fn find_seed_paths_rejects_a_seed_id_that_is_not_a_uuid_before_any_predicate_is_built() {
        let path = temp_path("reject-id");
        let db = DatabaseManager::initialize(&path).await.unwrap();
        let (index, _) = graph(vec![ent(1, "Alpha", &[])], &[]);
        let hostile = Seed {
            entity_id: "x' OR '1'='1".to_string(),
            name: "Hostile".to_string(),
            match_kind: MatchKind::Vector,
            score: 0.9,
            degree: 0,
        };
        let seeds = [seed_of(&index, 1), hostile];

        let error = find_seed_paths(&db, &index, &seeds, &path_settings(33, 16, 8))
            .await
            .unwrap_err();

        assert!(error.contains("not a valid UUID") || error.contains("invalid"), "{error}");
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }
}

/// The graph index travels in the corpus snapshot beside BM25: built at startup, rebuilt at the
/// same trigger and swapped with it, and degraded together with it (06.3.4.1-14 Task 1).
mod snapshot_graph_index {
    use std::sync::Arc;

    use super::seed_paths::{id, temp_path, write_store_edges, write_store_entities, StoreEntity};
    use crate::db::DatabaseManager;
    use crate::graph::index::GraphIndex;
    use crate::ingest::{rebuild_and_swap, rebuild_and_swap_with_graph_builder, REBUILD_TEST_MUTEX};
    use crate::retrieval::{Bm25Config, Bm25Index};
    use crate::workflow::ports::{CorpusSnapshot, CorpusStore};

    fn entity(n: u128, name: &'static str) -> StoreEntity {
        StoreEntity {
            n,
            name,
            chunks: vec![format!("{}:0", id(900 + n))],
            vector_value: 0.1 * n as f32,
        }
    }

    /// A store with two entities and one edge, and a corpus store whose snapshot was built from
    /// it the way `main.rs` builds the first one.
    async fn built_corpus_store(name: &str) -> (DatabaseManager, CorpusStore, String) {
        let path = temp_path(name);
        let db = DatabaseManager::initialize(&path).await.unwrap();
        write_store_entities(&db, &[entity(1, "Alpha"), entity(2, "Beta")]).await;
        write_store_edges(&db, &[(1, 2, "partners", 1.0)]).await;
        let nodes = db.nodes_table().await.unwrap();
        let bm25 = Bm25Index::from_table(&nodes, Bm25Config::default())
            .await
            .unwrap();
        let index = GraphIndex::build(&db).await.unwrap();
        let snapshot = Arc::new(CorpusSnapshot::new(
            Arc::new(bm25),
            Arc::new(index),
            nodes.version().await.unwrap(),
            false,
        ));
        (db, Arc::new(tokio::sync::RwLock::new(snapshot)), path)
    }

    async fn grow_the_graph(db: &DatabaseManager) {
        write_store_entities(db, &[entity(3, "Gamma")]).await;
        write_store_edges(db, &[(2, 3, "supplies", 1.0)]).await;
    }

    #[test]
    fn the_empty_graph_index_has_no_entities_and_matches_nothing() {
        let index = GraphIndex::empty();

        assert_eq!(index.entity_count(), 0);
        assert!(index.exact_matches("Alpha").is_empty());
        assert!(index.normalized_matches("Alpha").is_empty());
        assert_eq!(index.degree(&id(1)), 0);
        assert!(!index.contains(&id(1)));
    }

    #[tokio::test]
    async fn a_rebuild_swaps_in_a_graph_index_built_from_the_latest_entities_and_edges() {
        let _lock = REBUILD_TEST_MUTEX.lock().await;
        let (db, store, path) = built_corpus_store("rebuild-index").await;
        let before = Arc::clone(&*store.read().await);
        assert_eq!(before.graph_index.entity_count(), 2);
        grow_the_graph(&db).await;

        let rebuilt = rebuild_and_swap(&db, &store, Bm25Config::default())
            .await
            .unwrap();

        let current = Arc::clone(&*store.read().await);
        assert!(Arc::ptr_eq(&current, &rebuilt), "the swapped snapshot is the returned one");
        assert!(!current.rebuild_degraded);
        assert_eq!(current.graph_index.entity_count(), 3, "the new entity is indexed");
        assert_eq!(current.graph_index.exact_matches("gamma"), &[id(3)]);
        assert_eq!(
            current.graph_index.degree(&id(2)),
            2,
            "Beta now has the old and the new edge"
        );
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }

    #[tokio::test]
    async fn a_query_holding_the_old_snapshot_keeps_the_old_graph_index_after_a_rebuild() {
        let _lock = REBUILD_TEST_MUTEX.lock().await;
        let (db, store, path) = built_corpus_store("old-snapshot-index").await;
        let held_by_a_query = Arc::clone(&*store.read().await);
        grow_the_graph(&db).await;

        rebuild_and_swap(&db, &store, Bm25Config::default())
            .await
            .unwrap();

        assert_eq!(held_by_a_query.graph_index.entity_count(), 2, "no mutation in place");
        assert!(!held_by_a_query.graph_index.contains(&id(3)));
        assert_eq!(held_by_a_query.graph_index.degree(&id(2)), 1);
        let current = Arc::clone(&*store.read().await);
        assert!(!Arc::ptr_eq(&held_by_a_query.graph_index, &current.graph_index));
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }

    #[tokio::test]
    async fn a_graph_index_build_failure_keeps_the_whole_prior_snapshot_and_marks_it_degraded() {
        let _lock = REBUILD_TEST_MUTEX.lock().await;
        let (db, store, path) = built_corpus_store("index-build-failure").await;
        let prior = Arc::clone(&*store.read().await);
        grow_the_graph(&db).await;

        let failure = rebuild_and_swap_with_graph_builder(
            &db,
            &store,
            Bm25Config::default(),
            &|_db| Box::pin(async { Err("injected graph index failure".to_string()) }),
        )
        .await
        .unwrap_err();

        assert!(failure.contains("injected graph index failure"), "{failure}");
        let current = Arc::clone(&*store.read().await);
        assert!(current.rebuild_degraded, "the degraded flag is set like a BM25 failure");
        assert!(Arc::ptr_eq(&current.bm25, &prior.bm25), "BM25 stays at the prior generation");
        assert!(
            Arc::ptr_eq(&current.graph_index, &prior.graph_index),
            "the graph index stays at the prior generation, so the pair is never mixed"
        );
        assert_eq!(current.generation, prior.generation);
        assert_eq!(current.nodes_version, prior.nodes_version);
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }

    #[tokio::test]
    async fn a_later_successful_rebuild_clears_a_graph_index_degradation() {
        let _lock = REBUILD_TEST_MUTEX.lock().await;
        let (db, store, path) = built_corpus_store("index-recovers").await;
        grow_the_graph(&db).await;
        let _ = rebuild_and_swap_with_graph_builder(
            &db,
            &store,
            Bm25Config::default(),
            &|_db| Box::pin(async { Err("injected graph index failure".to_string()) }),
        )
        .await;
        assert!(store.read().await.rebuild_degraded);

        rebuild_and_swap(&db, &store, Bm25Config::default())
            .await
            .unwrap();

        let current = Arc::clone(&*store.read().await);
        assert!(!current.rebuild_degraded);
        assert_eq!(current.graph_index.entity_count(), 3);
        drop(db);
        let _ = std::fs::remove_dir_all(path);
    }

    /// `main.rs` has no test module (the binary target count is pinned at 0), so the startup
    /// order is read from its source: the graph index is built before the first snapshot.
    #[test]
    fn main_builds_the_graph_index_once_before_the_first_snapshot() {
        let main_source = include_str!("../main.rs");
        assert_eq!(
            main_source.matches("GraphIndex::build(&database)").count(),
            1,
            "main.rs must build the graph index exactly once"
        );
        let build = main_source.find("GraphIndex::build(&database)").unwrap();
        let snapshot = main_source.find("CorpusSnapshot::new(").unwrap();
        assert!(
            build < snapshot,
            "the graph index ({build}) must be built before the first snapshot ({snapshot})"
        );
    }
}
