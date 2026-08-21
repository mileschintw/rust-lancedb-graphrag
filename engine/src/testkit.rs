//! Protobuf message test constructors for additive contract growth.
//!
//! This module holds `cfg(test)` constructors for protobuf messages whose field
//! sets are expected to grow additively. Its purpose is to keep an additive
//! contract change from producing mechanical churn in the test tree.

use crate::pb::lancet::v1::{Notice, NoticeSeverity, QueryRagRequest};

pub fn test_query_request(query: &str, session_id: &str) -> QueryRagRequest {
    QueryRagRequest {
        query: query.to_string(),
        session_id: session_id.to_string(),
        ..Default::default()
    }
}

pub fn test_notice(code: &str, message: &str, severity: NoticeSeverity) -> Notice {
    Notice {
        code: code.to_string(),
        message: message.to_string(),
        severity: severity as i32,
        ..Default::default()
    }
}
