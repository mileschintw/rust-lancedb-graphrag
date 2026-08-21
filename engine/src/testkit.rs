//! Protobuf message test constructors for additive contract growth.
//!
//! This module holds `cfg(test)` constructors for protobuf messages whose field
//! sets are expected to grow additively. Its purpose is to keep an additive
//! contract change from producing mechanical churn in the test tree.

use crate::pb::lancet::v1::{Notice, NoticeCode, NoticeSeverity, QueryRagRequest};
use crate::workflow::notice;

pub fn test_query_request(query: &str, session_id: &str) -> QueryRagRequest {
    QueryRagRequest {
        query: query.to_string(),
        session_id: session_id.to_string(),
        ..Default::default()
    }
}

pub fn test_notice(code: NoticeCode, message: &str, severity: NoticeSeverity) -> Notice {
    notice(code, message, severity)
}
