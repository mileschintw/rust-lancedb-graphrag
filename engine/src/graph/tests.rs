use std::sync::Arc;

use arrow_array::{Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};

use super::bridge;
use super::{
    clamp_hop_cap, traverse_fixed_hop, traverse_filtered_by_relation_type, traverse_multi_hop,
    GraphSpikeErrorKind, MAX_HOP_CAP,
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
