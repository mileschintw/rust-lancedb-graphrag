//! Per-document evidence metadata held beside one corpus generation (Phase 06.3.6, D-142, D-145).
//!
//! A [`DocMetaMap`] names, per `document_id`, the publication, the real document title and the
//! publication date of a document. It is built once per corpus snapshot and never mutated, so a
//! query that holds the snapshot reads one consistent generation. Retrieval never reads it: the
//! `RetrieveHybrid` node attaches an entry to an evidence block only for a request that names the
//! `evidence_metadata` lever, after the final list is fixed, which is what keeps the lever's
//! retrieval equal to the lever-free request by construction.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

/// The optional metadata of one document; every field may be absent.
///
/// `published_date` holds the rendered `YYYY-MM-DD` date. The map stores what it is given: the
/// escaping that makes a value safe for the prompt happens once, in `encode_evidence_block`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocMeta {
    /// The real document title, as distinct from the sanitized filename kept in `title`.
    pub doc_title: Option<String>,
    /// The publication that carried the document.
    pub source: Option<String>,
    /// The publication date, `YYYY-MM-DD`.
    pub published_date: Option<String>,
}

impl DocMeta {
    /// Whether none of the three fields is present.
    pub fn is_blank(&self) -> bool {
        self.doc_title.is_none() && self.source.is_none() && self.published_date.is_none()
    }
}

/// An immutable map from `document_id` to the [`DocMeta`] of that document.
///
/// An empty map means the corpus carries no metadata, which makes the `evidence_metadata` lever
/// unavailable on this snapshot.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DocMetaMap {
    entries: HashMap<String, DocMeta>,
}

impl DocMetaMap {
    /// Builds a map from `(document_id, metadata)` pairs.
    ///
    /// An entry with no field present carries nothing to show and is not stored, so a document
    /// without metadata and a document with a blank entry are the same to the reader. A later
    /// pair for the same `document_id` replaces the earlier one.
    pub fn from_entries(entries: impl IntoIterator<Item = (String, DocMeta)>) -> Self {
        Self {
            entries: entries
                .into_iter()
                .filter(|(_, meta)| !meta.is_blank())
                .collect(),
        }
    }

    /// The metadata of `document_id`, or `None` when the document has none.
    pub fn get(&self, document_id: &str) -> Option<&DocMeta> {
        self.entries.get(document_id)
    }

    /// Whether no document has metadata.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// The number of documents that have metadata.
    pub fn len(&self) -> usize {
        self.entries.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn meta(title: Option<&str>, source: Option<&str>, date: Option<&str>) -> DocMeta {
        DocMeta {
            doc_title: title.map(str::to_owned),
            source: source.map(str::to_owned),
            published_date: date.map(str::to_owned),
        }
    }

    #[test]
    fn a_blank_entry_is_not_stored_and_a_present_one_is_found_by_document_id() {
        let map = DocMetaMap::from_entries([
            ("doc-a".to_owned(), meta(Some("A title"), None, None)),
            ("doc-b".to_owned(), DocMeta::default()),
        ]);
        assert_eq!(map.len(), 1);
        assert!(!map.is_empty());
        assert_eq!(map.get("doc-a").unwrap().doc_title.as_deref(), Some("A title"));
        assert!(map.get("doc-b").is_none(), "a blank entry carries nothing");
        assert!(map.get("doc-missing").is_none());
    }

    #[test]
    fn a_map_built_from_nothing_is_empty() {
        let map = DocMetaMap::from_entries(Vec::new());
        assert!(map.is_empty());
        assert_eq!(map.len(), 0);
        assert!(DocMetaMap::default().is_empty());
    }

    #[test]
    fn a_later_pair_for_one_document_replaces_the_earlier_one() {
        let map = DocMetaMap::from_entries([
            ("doc-a".to_owned(), meta(Some("first"), None, None)),
            ("doc-a".to_owned(), meta(None, Some("second"), None)),
        ]);
        let stored = map.get("doc-a").unwrap();
        assert_eq!(stored.doc_title, None);
        assert_eq!(stored.source.as_deref(), Some("second"));
    }
}
