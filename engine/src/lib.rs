extern crate self as engine;

pub mod chunker;
pub mod client;
pub mod config;
pub mod db;
pub mod generation;
pub mod graph;
pub mod ingest;
pub mod pb;
pub mod prompt;
pub mod rerank;
pub mod retrieval;
pub mod service;
pub mod workflow;

pub use pb::lancet::v1::lancet_service_server::LancetService;

#[cfg(test)]
#[path = "tests/workflow_phase5.rs"]
pub mod workflow_phase5;

#[cfg(test)]
pub mod tests;

#[cfg(test)]
pub mod testkit;
