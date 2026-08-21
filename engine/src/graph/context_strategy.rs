//! Knowledge graph context assembly strategies and GraphFact representation.

use serde::Serialize;

/// Strategy governing how extracted knowledge graph facts are assembled into prompt text.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize)]
pub enum ContextAssemblyStrategy {
    PrecomputedSemantics,
    #[default]
    SourceChunks,
}

/// A structured graph fact representing a directed relationship triple between two entities.
///
/// Note on escaping: String fields (`entity_a_name`, `relation_type`, `entity_b_name`, `edge_summary`)
/// are kept private and are unconditionally HTML-entity-escaped upon construction in [`GraphFact::new`].
/// Do not re-escape these values at render time — `encode_field_value` is not idempotent (a second pass
/// would turn `&amp;` into `&amp;amp;`). Construction-time escaping guarantees no unescaped instance
/// can exist in the system.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GraphFact {
    entity_a_name: String,
    relation_type: String,
    entity_b_name: String,
    edge_summary: Option<String>,
    pub score: f64,
}

impl GraphFact {
    pub fn new(
        entity_a_name: &str,
        relation_type: &str,
        entity_b_name: &str,
        edge_summary: Option<&str>,
        score: f64,
    ) -> Self {
        Self {
            entity_a_name: crate::prompt::escape_evidence_delimiters(entity_a_name),
            relation_type: crate::prompt::escape_evidence_delimiters(relation_type),
            entity_b_name: crate::prompt::escape_evidence_delimiters(entity_b_name),
            edge_summary: edge_summary.map(crate::prompt::escape_evidence_delimiters),
            score,
        }
    }

    pub fn entity_a_name(&self) -> &str {
        &self.entity_a_name
    }

    pub fn relation_type(&self) -> &str {
        &self.relation_type
    }

    pub fn entity_b_name(&self) -> &str {
        &self.entity_b_name
    }

    pub fn edge_summary(&self) -> Option<&str> {
        self.edge_summary.as_deref()
    }
}

impl ContextAssemblyStrategy {
    pub fn assemble(&self, fact: &GraphFact) -> String {
        match self {
            Self::SourceChunks => format!(
                "{} —{}→ {}",
                fact.entity_a_name(),
                fact.relation_type(),
                fact.entity_b_name()
            ),
            Self::PrecomputedSemantics => {
                if let Some(summary) = fact.edge_summary() {
                    summary.to_string()
                } else {
                    format!(
                        "{} —{}→ {}",
                        fact.entity_a_name(),
                        fact.relation_type(),
                        fact.entity_b_name()
                    )
                }
            }
        }
    }
}
