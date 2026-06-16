# Shrag 🚀

**Shrag** is an end-to-end, high-performance, systems-oriented Retrieval-Augmented Generation (RAG) and GraphRAG platform. Built to showcase robust systems engineering and data-plane design, it employs a split-service architecture that separates a user-facing control plane from a high-performance, custom-built data plane.

The architecture splits responsibilities between a user-facing **Go API Gateway** (handling routing, metadata, and orchestration API) and a low-latency, computationally optimized **Rust RAG Engine** (handling document chunking, hybrid retrieval, and knowledge graph traversal). Communication between them is orchestrated via **gRPC** over a structured Protobuf contract.

---

## 🏗️ Architecture Overview

The diagram below illustrates the split-service architecture, storage strategies, and observability integration:

```mermaid
graph TD
    User([User / Client]) -->|HTTP REST| GoGateway[Go API Gateway <br> Control Plane]
    GoGateway -->|gRPC / Protobuf| RustEngine[Rust RAG Engine <br> Data Plane]
    
    subgraph Control Plane Storage
        GoGateway -->|SQL| Postgres[(PostgreSQL <br> Sessions & Metadata)]
    end
    
    subgraph Data Plane Components
        RustEngine --> Chunker[Custom Chunker]
        RustEngine --> Store[LanceDB <br> Embedded Vector Store]
        RustEngine --> GraphStore[lance-graph <br> Native LanceDB Graph Engine]
        RustEngine --> Retriever[Hybrid Retriever <br> Dense Vector + BM25]
        RustEngine --> Orchestrator[Lightweight State Machine]
    end

    subgraph Observability & Eval
        GoGateway -.->|OTel Traces| Jaeger[(Jaeger Tracer)]
        RustEngine -.->|OTel Traces| Jaeger
        EvalScript[eval.py <br> LLM-as-a-judge] -.->|Queries| GoGateway
    end
```

---

## ✨ Core Features & Technical Highlights

Unlike boilerplate RAG wrappers, Shrag features custom data-plane components built from the ground up in Rust to demonstrate high-level systems design:

1. **Custom Structure-Aware Chunker:** A recursive parser processing heterogeneous document formats (Markdown, JSON, text, etc.) into clean, semantic chunk structures rather than using arbitrary character-count windows.
2. **Hybrid Vector & Lexical Retriever:** A query composer that combines embedded **LanceDB** dense vector searches with a local, in-memory **BM25 lexical index** and metadata filters.
3. **GraphRAG Traverser:** A GraphRAG orchestrator utilizing `lance-graph` (the native LanceDB graph engine) to store entities and relationships as Arrow tables, execute Cypher queries to extract relevant subgraphs, and compile prompt contexts.
4. **gRPC Interface:** Seamless, type-safe inter-service communication defined in [shrag.proto](file:///c:/Users/user3/Shrag/proto/shrag.proto) utilizing `tonic` (Rust) and `google.golang.org/grpc` (Go).
5. **Distributed Tracing (OpenTelemetry):** Native instrumentation across both Go and Rust boundaries, tracing request lifecycles from the HTTP gateway down to vector search queries and LLM invocations.
6. **Automated Offline Evaluation:** A Python benchmarking tool utilizing an **LLM-as-a-judge** setup to measure retrieval recall, context precision, and response faithfulness.

---

## 🛠️ Technology Stack

| Layer | Technology | Rationale / Detail |
| :--- | :--- | :--- |
| **Control Plane** | Go (Gin / standard library) | Fast, light backend services, simple concurrency, and rapid API routing. |
| **Data Plane** | Rust (Tokio, Tonic) | Memory safety, zero-cost abstractions, maximum concurrency, and low latency. |
| **Vector Database** | LanceDB (Embedded) | Serverless, Arrow-native vector retrieval with negligible runtime overhead. |
| **Graph Operations** | `lance-graph` | Native LanceDB graph query engine supporting Cypher queries over Arrow tables. |
| **Metadata Store** | PostgreSQL | Relational storage for user accounts, session states, and document schemas. |
| **Observability** | OpenTelemetry / Jaeger | Complete distributed tracing across boundaries to isolate latency bottlenecks. |
| **Evaluation** | Python | Standard ML/LLM scripting harness for running validation tests. |

---

## 📂 Project Directory Structure

```text
Shrag/
├── proto/
│   └── shrag.proto               # Shared gRPC service definitions
├── engine/                       # Rust RAG Engine (Data Plane)
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs               # gRPC server bootstrap & tracing config
│       ├── chunker.rs            # Structure-aware recursive chunker
│       ├── store.rs              # LanceDB driver and vector retrieval
│       ├── graph.rs              # Entity-relation mapping and Cypher query interface using lance-graph
│       ├── retriever.rs          # BM25 + LanceDB hybrid query engine
│       └── orchestrator.rs       # RAG state-machine and LLM orchestrator
├── gateway/                      # Go API Gateway (Control Plane)
│   ├── go.mod
│   ├── main.go                   # HTTP handlers (REST) and gRPC client
│   └── db.go                     # PGX connection, authentication & session storage
├── eval/
│   └── eval.py                   # LLM-as-a-judge benchmarking script
├── docker-compose.yml            # Infra (Postgres, Jaeger, local services)
└── README.md                     # Project overview and run instructions
```

---

## 🚀 Getting Started

### Prerequisites

- [Go](https://go.dev/) (v1.20+)
- [Rust & Cargo](https://www.rust-lang.org/) (Edition 2021)
- [Docker & Docker Compose](https://www.docker.com/)
- [Python 3.10+](https://www.python.org/) (for offline evaluation)
- API Keys for your preferred LLM provider (e.g., OpenAI, Anthropic, or Gemini) set as environment variables.

### Step 1: Start Infrastructure Containers

Spin up the metadata database (PostgreSQL) and the tracing collector (Jaeger):

```bash
docker compose up -d
```

### Step 2: Configure Environment Variables

Create a local `.env` configuration or export the following keys:

```bash
export OPENAI_API_KEY="your-api-key" # Or Gemini/Anthropic depending on engine setup
export DATABASE_URL="postgres://user:password@localhost:5432/shrag"
export ENGINE_GRPC_ADDR="localhost:50051"
```

### Step 3: Run the Rust RAG Engine

From the `engine/` directory, compile and launch the gRPC data plane:

```bash
cd engine
cargo run --release
```

The engine will spin up its gRPC server listening on port `50051`.

### Step 4: Run the Go API Gateway

From the `gateway/` directory, run the control plane HTTP server:

```bash
cd gateway
go run main.go
```

The gateway will run on port `8080`, exposing the following endpoints:
- `POST /v1/documents` - Upload and index heterogeneous documents.
- `POST /v1/query` - Request a RAG pipeline response.
- `GET /v1/graph` - Retrieve mapped graph entities and subgraphs.

---

## 📊 Evaluation & Tracing

### Distributed Tracing with Jaeger

Shrag features full OpenTelemetry tracing. When you query the system, traces are collected automatically. 

1. Access the Jaeger UI at `http://localhost:16686` in your browser.
2. Select `gateway` or `engine` from the service list.
3. Analyze detailed trace flows to pinpoint parsing latency, gRPC trip times, vector retrieval performance, or downstream LLM completion times.

### Offline LLM-As-A-Judge Evaluation

To measure retrieval accuracy and generated output metrics:

1. Navigate to the `eval/` directory.
2. Install Python dependencies: `pip install -r requirements.txt` (or install `openai` and `pandas`).
3. Run the evaluation script:

```bash
python eval/eval.py
```

The script will query the Go Gateway, run a test corpus through the system, run evaluations on Context Precision, Retrieval Recall, Groundedness, and Faithfulness, and print a formatted summary table.
