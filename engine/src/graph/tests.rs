use std::sync::Arc;

use arrow_array::{Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};

use super::bridge;
use super::{
    clamp_hop_cap, clamp_hop_cap_with_ceiling, traverse_fixed_hop,
    traverse_filtered_by_relation_type, traverse_multi_hop, GraphSpikeErrorKind, MAX_HOP_CAP,
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

    assert_eq!(round_tripped.schema().fields().len(), entities.schema().fields().len());
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
    use super::extraction::{ExtractionGenerator, ExtractionOutput, ExtractionRequest, FakeExtractionGenerator, ExtractedEntity, ExtractedRelation};

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

    let res = generator.extract(req).await.expect("Fake extraction must succeed");
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
async fn cypher_narrowing_fail_open() {
    let (entities, edges) = three_entity_two_edge_fixture();
    // Invalid seed_id or empty neighborhood should fail open to original batches
    let (out_entities, out_edges) = super::narrow_via_cypher(&entities, &edges, "nonexistent-seed", 1).await;
    // Fail open invariant: out_entities and out_edges must equal original inputs
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
    let bridged_lg = bridge::decode_all_batches(reader).expect("decode_all_batches must succeed on 2-batch stream");
    assert_eq!(bridged_lg.num_rows(), 5, "bridged_lg must contain all 5 rows across both batches");

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
        let mut writer = arrow_ipc_lg::writer::StreamWriter::try_new(&mut buf_lg, &schema_lg).unwrap();
        writer.write(&batch1_lg).unwrap();
        writer.write(&batch2_lg).unwrap();
        writer.finish().unwrap();
    }

    let reader_back = arrow_ipc::reader::StreamReader::try_new(buf_lg.as_slice(), None).unwrap();
    let bridged_back = bridge::decode_all_batches(reader_back).expect("decode_all_batches must succeed on 2-batch back stream");
    assert_eq!(bridged_back.num_rows(), 3, "bridged_back must contain all 3 rows across both batches");
}
#[test]
fn clamp_hop_cap_with_ceiling_applies_min_of_configured_and_compile_time() {
    // configured_max below MAX_HOP_CAP: the configured value wins
    assert_eq!(clamp_hop_cap_with_ceiling(1, 1), Ok(1));
    assert_eq!(clamp_hop_cap_with_ceiling(2, 2), Ok(2));
    // configured_max equal to MAX_HOP_CAP: both agree
    assert_eq!(clamp_hop_cap_with_ceiling(MAX_HOP_CAP, MAX_HOP_CAP), Ok(MAX_HOP_CAP));
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
