# Lancet: Final Implementation Decision Document

This document summarizes the finalized architectural, storage, and design decisions for the **Lancet** project, as resolved during the `/grill-me` interactive planning session.

---

## 1. Project Identity & Target Role Alignment
* **Primary Target (Identity A & D - Systems/Infrastructure):** Focus is on showcasing systems-level capabilities, concurrency, memory safety, performance, and custom data-plane components.
* **Secondary Target (Identity C - Agentic Retrieval):** Demonstrate workflow control and GraphRAG harness/tool engineering.
* **Lowest Priority (Identity B - Platform Utility):** The product-facing shell and session APIs will utilize Go and standard external tools to minimize implementation friction.

---

## 2. Architecture & Service Boundaries
* **Split-Service Architecture:** A clear separation between the control plane and data plane.
  * **Go API Gateway (Control Plane):** Handles the HTTP API, user authentication, session state, and metadata storage (relational DB).
  * **Rust RAG Engine (Data Plane):** Handles computationally heavy and latency-sensitive tasks, including document parsing, custom chunking, hybrid vector retrieval, graph traversal, and agentic LLM orchestration.
* **Inter-Service Communication:** Services communicate via **gRPC** over a structured Protobuf schema.

---

## 3. Storage & Vector Database Strategy
* **Vector Store:** **LanceDB** embedded directly within the Rust service to enable fast, local-first, Arrow-native vector retrieval with minimal deployment overhead.
* **Graph Database:** Nodes (chunks/entities) and edges (extracted relations) stored directly in LanceDB tables and queried natively using the `lance-graph` engine with Cypher.
* **Metadata Database:** PostgreSQL (or local SQLite fallback) managed by the Go API Gateway to store user accounts, sessions, and document metadata.

---

## 4. Custom vs. Framework Focus (Rust Engine)
To maximize systems engineering signaling, the core RAG components will be custom-built rather than relying on black-box frameworks:
1. **Custom Chunking:** A structure-aware, recursive chunker parsing heterogeneous documents (Markdown, JSON, text, etc.) into clean semantic units.
2. **Custom Hybrid Retrieval:** A query composer that combines LanceDB dense vector search, a local lexical index (e.g., BM25), and metadata filters.
3. **Custom GraphRAG Orchestrator:** A GraphRAG query and context compiler in Rust utilizing `lance-graph` to execute Cypher pattern-matching queries over LanceDB, extract relevant subgraphs, and compile prompt contexts.
4. **Standard Crates:** Standard libraries (e.g., `tonic` for gRPC, `reqwest` for HTTP, `serde` for serialization) are used for basic network and serialization scaffolding.

---

## 5. Ingestion & Data Sources
* **heterogeneous Data Sources:** General-purpose design to ingest, parse, and chunk multiple document types rather than targeting a single hardcoded schema.
* **Entity-Relation Extraction:** During ingestion, an LLM extracts key entities and relationships from chunks, persisting them to construct the graph.

---

## 6. Observability & Evaluation
* **Distributed Tracing:** Both Go and Rust services are instrumented with **OpenTelemetry**, exporting spans to a local **Jaeger** collector to provide end-to-end gRPC and LLM latency traces.
* **Offline Evaluation:** An offline Python-based **LLM-as-a-judge** evaluation script to measure retrieval recall, context precision, and answer faithfulness against a test dataset.

---

## 7. Build & Local Development Strategy
* **Hybrid Local-First:** Run Go and Rust services directly on the host machine (`go run` / `cargo run`) for rapid development feedback loops.
* **Docker Compose:** Used to spin up external supporting services (PostgreSQL, Jaeger) in a production-like environment.
