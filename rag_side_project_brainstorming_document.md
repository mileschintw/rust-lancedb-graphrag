# End-to-End RAG Side Project Brainstorming and Planning Document

## Purpose and use of this document

This document is designed as a working artifact for brainstorming, technical discussion, architecture review, and implementation planning for a resume-oriented side project centered on Retrieval-Augmented Generation (RAG), AI agents, data systems, and infrastructure. It is intentionally expansive rather than narrow: it preserves multiple candidate directions, competing tool choices, architectural variants, and trade-off discussions without forcing a final decision on the stack, the product shape, or the implementation path. The goal is to support productive discussion with other engineers, mentors, hiring managers, and AI systems before locking in a final project plan.[cite:1][cite:10][cite:25]

The project context assumed throughout this document is a candidate who is more attracted to infrastructure and databases than to purely application-layer work, but who does not want to go all-in on low-level database internals. The motivating idea is to use a RAG-centric side project to create a portfolio piece that is attractive in the North American engineering market by combining practical AI relevance with stronger systems and data-engineering signals than a standard Python wrapper project would provide.[cite:1][cite:10][cite:25][cite:47]

This document therefore keeps all serious proposals on the table: a pure Rust implementation, a Go-and-Rust split architecture, different vector database options, different orchestration styles, alternative ingestion and indexing approaches, multiple evaluation and observability strategies, and both framework-heavy and framework-light implementation routes. It also explicitly distinguishes where existing tools should probably be adopted versus where custom implementation can better signal engineering ability on a resume.[cite:3][cite:21][cite:52][cite:56][cite:61]

## Project goals

The side project can serve several overlapping goals rather than just one. One goal is market relevance: RAG, AI agents, vector retrieval, and LLM infrastructure remain highly visible areas of hiring demand, especially for teams moving from prototype systems to production-grade workflows.[cite:25][cite:47][cite:66] Another goal is technical differentiation: using Rust or a Rust-centered architecture creates a stronger systems signal than a conventional Python-only project, especially when the implementation clearly addresses concurrency, latency, type safety, and memory management concerns.[cite:10][cite:47][cite:50]

A third goal is narrative coherence on the resume. A project is more valuable when it extends an existing story rather than starting an unrelated one. For a candidate with backend, distributed systems, observability, ML, or AI-adjacent experience, a RAG system built with explicit attention to retrieval quality, structured evaluation, tracing, and throughput can connect application-layer AI work to infrastructure thinking in a way that is legible to North American employers.[cite:25][cite:66][cite:69]

A fourth goal is discussion quality. The project should be rich enough that it can support serious conversations about architectural trade-offs: control plane versus data plane, online versus offline evaluation, pluggable storage abstractions, hybrid retrieval, reranking, document chunking strategy, multi-step orchestration, streaming responses, and deployment shape. That kind of discussion value matters because a strong side project is often more useful as an interview artifact than as a literal commercial product.[cite:52][cite:58][cite:64][cite:71]

## What “good” looks like for this project

For this project to be attractive on a resume, it does not need to outperform commercial RAG products or replace mature frameworks. It needs to show clear engineering judgment. That usually means a design that is narrow enough to complete but deep enough to reveal trade-offs, performance awareness, and systems structure.[cite:10][cite:47][cite:64]

A strong version of the project would have the following visible characteristics:

- A clearly defined end-to-end architecture from ingestion to retrieval to answer generation to evaluation.[cite:64][cite:66][cite:69]
- At least one explicit design choice motivated by systems concerns such as latency, memory safety, failure handling, streaming, or concurrency.[cite:10][cite:47][cite:84]
- At least one area where custom implementation replaces a black-box framework in order to demonstrate understanding of an important core mechanism, such as chunking, retrieval composition, or orchestration state management.[cite:52][cite:58][cite:64]
- At least one area where the project intentionally adopts existing tools instead of reimplementing them, showing practical judgment rather than unnecessary reinvention.[cite:21][cite:51][cite:57]
- A README or design document that articulates alternatives considered, trade-offs, evaluation criteria, and future directions.[cite:64][cite:65][cite:74]

## Candidate project identities

This project can be framed in more than one way depending on what identity should be emphasized on the resume.

### Identity A: High-performance RAG engine

In this framing, the project’s center of gravity is the retrieval engine and the internal execution model. The main emphasis is on document ingestion, chunking, indexing, hybrid retrieval, reranking, LLM context construction, and low-latency orchestration. This framing is most aligned with infrastructure, databases, search, systems programming, and AI infra roles.[cite:10][cite:21][cite:53][cite:64]

### Identity B: End-to-end RAG platform

In this framing, the project is presented as a product-shaped system rather than just an engine. It includes user-facing API endpoints, session handling, document management, observability, evaluation dashboards, and potentially a lightweight web UI. This framing is especially useful when applying to backend or platform roles where productization and user-facing API design are also valued.[cite:66][cite:69][cite:72]

### Identity C: Agentic retrieval system

In this framing, the project highlights workflow orchestration and reasoning structure rather than static retrieval alone. The system may rewrite queries, choose tools, retrieve from multiple corpora, rerank evidence, maintain conversation memory, and perform confidence-based fallback behaviors such as reformulating the query or invoking web search. This framing is useful when targeting AI platform or agent infrastructure roles.[cite:52][cite:58][cite:63][cite:64]

### Identity D: Resume-first engineering artifact

In this framing, the project is optimized for signaling rather than market competition. The design is intentionally chosen to demonstrate competence in several valuable areas at once: systems design, modern AI stack familiarity, observability, evaluation rigor, and sensible tool selection. This identity is especially relevant if the main goal is interview leverage rather than open-source adoption or startup validation.[cite:25][cite:47][cite:64]

These identities are not mutually exclusive. The final implementation could blend them, but separating them at planning time helps clarify which features are essential versus optional.

## The end-to-end RAG stack: a planning model

A useful way to reason about the project is as a set of separable layers. Real-world RAG systems are usually composed from multiple independently evolving subsystems rather than a single monolithic framework.[cite:64][cite:66][cite:73]

The major layers are:

1. Source data acquisition and storage.
2. Document parsing and normalization.
3. Chunking and structural segmentation.
4. Embedding generation and indexing.
5. Retrieval and metadata filtering.
6. Reranking and evidence consolidation.
7. Prompt/context assembly.
8. LLM generation and tool orchestration.
9. Conversation memory and state management.
10. Evaluation, observability, tracing, and deployment.

This layered model is important because it supports selective reinvention. The project does not have to rebuild every layer from scratch. It can instead choose one or two layers as the core “custom engineering” areas while using mature tools elsewhere.[cite:3][cite:21][cite:52][cite:64]

## Market landscape and competitor map

### Why RAG remains relevant

RAG remains attractive because organizations still need ways to make LLM systems useful over private, fast-changing, or domain-specific information without full model retraining. Job demand and tooling activity continue to cluster around vector retrieval, agent orchestration, evaluation, and production observability, especially as teams move from proof-of-concept systems to production use.[cite:25][cite:47][cite:66][cite:72]

For a side project, the implication is that building a thoughtful RAG system still signals current relevance. However, a generic “chat with PDFs” clone has low differentiation. The more compelling version is one that makes strong choices about retrieval quality, engine design, orchestration, or performance.[cite:21][cite:64][cite:73]

### Main categories of competitors

The project will implicitly compete, at least in perception, with several classes of existing tools:

- Managed vector databases and RAG backends.[cite:51][cite:54][cite:57][cite:62]
- AI application frameworks and orchestration frameworks such as LangChain and LangGraph.[cite:52][cite:58][cite:63]
- Rust-specific LLM application frameworks such as Rig.[cite:3][cite:56][cite:61]
- Turnkey RAG products and UI-first systems such as hosted “chat over docs” tools.[cite:67]
- Evaluation and observability platforms such as LangSmith, TruLens, and related tools.[cite:65][cite:66][cite:69][cite:72][cite:74]

A resume-oriented side project does not need to beat these products directly. Instead, it should show a mature understanding of how such systems are composed and where important trade-offs exist.

## Vector database and storage landscape

Vector storage is one of the most visible choices in the RAG stack, but it should not dominate the entire project narrative. Industry comparisons repeatedly highlight Pinecone, Weaviate, Qdrant, Chroma, Milvus, pgvector, and LanceDB as major options, each with distinct trade-offs around managed service maturity, local development experience, metadata support, hybrid retrieval, and operational complexity.[cite:51][cite:54][cite:57][cite:60][cite:62]

### Pinecone

Pinecone represents the fully managed end of the spectrum. Its main value proposition is low operational burden and cloud-managed scaling. That is attractive for production teams optimizing for delivery speed, but it is less useful as the central differentiator in a side project intended to showcase infrastructure thinking, because much of the hard systems work is abstracted away.[cite:51][cite:57][cite:60]

### Weaviate

Weaviate is a strong open-core and managed option with notable support for hybrid retrieval, metadata-aware querying, and a richer schema story than some lighter-weight systems. It is useful when the project needs structured attributes, semantic search, and text retrieval in the same environment. It can also serve as a conceptual reference even if not selected, because its design makes visible how retrieval systems often combine vector similarity with richer filtering and ranking logic.[cite:51][cite:54][cite:62]

### Qdrant

Qdrant is especially interesting in this project context because it is Rust-based and often associated with strong performance and practical production deployment for vector search and hybrid retrieval workloads. It can be a very strong fit for a Rust-centered RAG project, especially if the goal is to signal systems alignment rather than use a Python-native tool by default.[cite:51][cite:57][cite:62]

### Chroma

Chroma is often attractive for experimentation, quick prototyping, and developer ergonomics, especially in Python ecosystems. For a Rust-focused side project, it is less compelling as the main engine, but it can still be useful as a comparison baseline or as a reminder that not every component needs to be native to one language.[cite:51][cite:54][cite:57]

### LanceDB

LanceDB is one of the most interesting options for a Rust-oriented side project because it supports an embedded, local-first mode and aligns well with the Arrow ecosystem. It can enable a setup that feels closer to SQLite-style local development for vector search while still supporting a technically rich story around indexing, storage, and efficient data access.[cite:21][cite:36][cite:53]

### pgvector and relational options

Although not emphasized as heavily in the recent comparison sources gathered here, relational options such as PostgreSQL with pgvector remain strategically relevant to side projects because they let a system combine traditional metadata, relational state, and vector search in one place. Even if not chosen as the primary retrieval engine, they remain worth discussing as a simplification option or as part of a hybrid design.[cite:54][cite:57]

### Storage decision space for this project

From a planning perspective, the main storage directions worth keeping alive are:

- Embedded local vector store with LanceDB.[cite:21][cite:36][cite:53]
- Self-hosted or managed vector service with Qdrant.[cite:51][cite:57][cite:62]
- General-purpose relational base with PostgreSQL and optional vector support.[cite:54][cite:57]
- Dual-store architecture: relational system for users and metadata, vector engine for retrieval.

For resume signaling, the best storage choice is not necessarily the most sophisticated one. The right choice is the one that allows the project to demonstrate understanding of retrieval, filtering, and indexing without drowning in operational setup.

## Document ingestion and parsing landscape

RAG systems are often judged by the answer quality, but a great deal of answer quality depends on ingestion quality. The system cannot retrieve well from poorly parsed or poorly segmented documents. Recent RAG guidance and production discussions repeatedly emphasize that early-stage ingestion and chunking decisions strongly influence downstream performance.[cite:64][cite:67][cite:76]

The project can ingest several possible source types:

- Markdown files.
- Plain text.
- HTML pages.
- CSV and tabular sources.[cite:5][cite:21]
- PDFs, with caveats around extraction quality.
- Code repositories.
- Internal notes or synthetic knowledge bases built for evaluation.

A planning question worth preserving is whether the system should be designed as domain-specific from the start. A domain-specific ingestion design often makes the project stronger because it allows more thoughtful chunking, metadata extraction, and evaluation. Generic ingestion is broader, but often becomes shallow.

## Chunking strategy landscape

Chunking is one of the highest-leverage parts of a RAG system. Multiple recent sources stress that chunking quality can have outsized impact on retrieval effectiveness, and that structure-aware chunking often outperforms naive fixed-size slicing.[cite:64][cite:70][cite:76]

### Fixed-size chunking

This is the simplest baseline. The system splits text by approximate token count or character count, often with overlap. It is easy to implement, easy to benchmark, and useful as a control condition. Typical practical guidance places chunk size in the 256 to 512 token range with 10 to 20 percent overlap, though exact settings depend on the domain and retrieval model.[cite:64][cite:76]

### Recursive or heuristic chunking

This approach attempts to split first by larger boundaries such as sections or paragraphs and only falls back to smaller cuts when needed. It tends to preserve semantics better than naive fixed-width splitting while remaining relatively easy to implement.[cite:64][cite:76]

### Structure-aware chunking

This approach uses explicit document structure such as Markdown headings, HTML tags, section boundaries, code blocks, table boundaries, or list structure. Sources discussing advanced RAG optimization repeatedly note that preserving document structure can materially improve answer grounding and retrieval relevance over simplistic slicing strategies.[cite:64][cite:76]

### Hierarchical chunking and indexing

This approach builds retrieval at multiple granularities. The system might first search coarse units like sections, then refine to paragraphs or sentences within top-ranked sections. This is conceptually aligned with hierarchical indexing and some advanced RAG designs that try to improve both recall and context coherence.[cite:64][cite:67]

### Semantic or similarity-aware chunk boundaries

A more advanced direction is to place chunk boundaries at semantic discontinuities rather than purely by length. This can be valuable for research depth and technical uniqueness, but it also introduces more complexity in boundary detection and evaluation.

### What this means for the project

Chunking is one of the best candidates for custom implementation because it is important, technically discussable, and feasible to build without recreating a whole vector database or model stack. A side project that includes multiple chunking strategies and an experiment comparing them would be significantly more compelling than one that delegates all segmentation to a black-box library.[cite:64][cite:76]

## Embeddings and retrieval models

The project does not need to train its own embeddings to be technically impressive. In most side-project scenarios, that would be a poor use of time relative to improvements in chunking, retrieval composition, evaluation, and engine design. Mature embedding APIs or existing embedding models are usually the more practical choice.[cite:3][cite:5][cite:61]

However, the planning document should keep open several choices:

- Hosted embeddings via OpenAI or a similar provider.
- Self-hosted embeddings if portability or cost control becomes important.
- Different embeddings for indexing versus reranking.
- Domain-tuned embeddings for specialized corpora.

The more important design question is not just “which embedding model” but “how are retrieved candidates composed, filtered, reranked, and passed into the LLM.” That is where much of the system behavior becomes interview-worthy.[cite:64][cite:73]

## Retrieval architecture landscape

Simple vector top-K retrieval is no longer considered sufficient for many realistic RAG workloads. Recent discussions of realistic RAG stacks often point toward hybrid retrieval, metadata filtering, deduplication, reranking, and confidence-based fallback behaviors.[cite:64][cite:67][cite:71][cite:73]

### Dense vector retrieval

This is the baseline semantic retrieval mechanism. It works well for paraphrase and semantic similarity, but it can miss rare keywords, identifiers, and exact string constraints.

### Sparse lexical retrieval

Keyword- and BM25-style search remain valuable because they capture exact terminology, IDs, and literals that embeddings may not preserve strongly. In practical stacks, dense and sparse methods are often combined rather than treated as substitutes.[cite:64][cite:73]

### Hybrid retrieval

Hybrid retrieval combines semantic and lexical methods. This has become one of the dominant real-world patterns because it improves coverage across both semantically fuzzy queries and exact-match-heavy queries.[cite:64][cite:71][cite:73]

### Metadata-aware filtering

Production RAG systems often need to filter by timestamp, tenant, language, document type, source system, or user scope before ranking results. This is a key reason why vector search rarely lives in isolation from richer metadata handling.

### Multi-stage retrieval

A strong design may retrieve a broad candidate set cheaply, then apply reranking or a second-stage refinement over the top results. This can improve answer quality while keeping total cost manageable.[cite:64][cite:70]

### Fallback and correction patterns

Some advanced systems use confidence scores or retrieval diagnostics to trigger fallback behavior: query rewriting, wider retrieval, alternative corpora, or external search. This is a useful planning direction for an “agentic retrieval” variant of the project.[cite:64]

## Reranking landscape

Reranking has become an important differentiator in realistic RAG systems. The broad pattern is to use a cheaper retrieval stage to find candidates and then apply a stronger but more expensive ranking stage to sort them.[cite:64][cite:70][cite:71]

Possible reranking approaches include:

- No reranking, relying only on retrieval scores.
- Lightweight heuristic reranking using metadata or length penalties.
- Cross-encoder reranking via an external service or model.[cite:64]
- LLM-as-reranker, where the language model itself judges which chunks best answer the question.[cite:64][cite:70]

Cross-encoder reranking is often a practical sweet spot because it improves ranking quality without the full latency and cost of asking a large model to evaluate all candidates. LLM reranking can be more flexible but usually increases latency substantially.[cite:64][cite:70]

For a side project, reranking is another high-value place to show engineering design. Even a pluggable rerank interface with two or three strategies can be enough to show systems awareness.

## Prompt construction and context assembly

One of the less visible but highly consequential parts of a RAG system is how retrieved evidence is turned into LLM input. Prompt construction is not just formatting. It is effectively the point where retrieval quality, token budgeting, source attribution, and generation control all meet.

Key planning dimensions include:

- How many chunks to include.
- Whether to preserve section order or score order.
- Whether to deduplicate semantically overlapping chunks.
- Whether to attach metadata like source title, section heading, or timestamp.
- Whether to include confidence hints or system instructions about abstention.
- Whether to generate citations or source references in the answer.

This area is often less glamorous than retrieval, but it is one of the places where a thoughtful implementation can dramatically improve groundedness and readability.[cite:65][cite:66]

## Orchestration and LLM piping landscape

There is now a rich landscape of orchestration frameworks for LLM workflows. The main comparison is not simply “which one is best” but “which ones expose ideas worth borrowing versus which ones should be used directly.”

### LangChain and LangGraph

LangChain remains one of the best-known framework families in the LLM application space, but for complex stateful agent workflows the center of gravity has moved toward LangGraph, which models workflows as explicit graph/state-machine systems with support for memory, human-in-the-loop steps, and durable execution.[cite:52][cite:58]

From a project-planning perspective, LangGraph matters even if it is not used because it provides a conceptual model for how to structure agent workflows explicitly rather than burying them in chained function calls.

### AutoGen, CrewAI, and multi-agent toolkits

These ecosystems focus more heavily on multi-agent coordination, role separation, and conversational task decomposition.[cite:63] They are useful references if the project wants to explore more than one cooperating agent, but they can easily make a side project too broad unless multi-agent structure is central to the learning goal.

### LlamaIndex and related stacks

These tools often emphasize data connectors, indexing, retrieval abstractions, and document-centric application assembly. They are conceptually useful, though the strongest project signal in this context may come from understanding their patterns rather than fully depending on them.

### Rust orchestration options: Rig and related approaches

Rig is a notable Rust framework for building LLM-powered applications with an emphasis on modularity and ergonomics. Its abstractions around clients, models, embeddings, agents, and vector store integration make it one of the most obvious building blocks for a Rust-centered RAG or agent project.[cite:3][cite:56][cite:61]

The main project question is therefore not whether Rig is good enough, but whether it should serve as the full application skeleton or only as a lower-level model access layer beneath a custom orchestration runtime.

## Memory and state management landscape

RAG systems increasingly overlap with agent systems, which means memory design matters. Memory can mean several different things, and failing to distinguish them often creates conceptual confusion.

Relevant memory types include:

- Conversation history memory for chat continuity.[cite:28]
- Retrieval memory, where prior answers or prior retrieval outputs influence future queries.
- User profile or preference memory.
- Long-term factual memory stored as indexed documents.
- Execution state memory used to coordinate multi-step workflows.

If the project includes conversational behavior, it should be explicit about which memory types are supported and how they are stored. For example, user-facing conversation memory could live in PostgreSQL, while retrieval memory could be represented as additional indexed chunks or summaries, and execution state could live in an in-memory state machine.

## Evaluation landscape

Evaluation is one of the clearest ways to elevate a RAG project beyond demo quality. The recent ecosystem includes several recurring evaluation concepts: context relevance, answer relevance, groundedness, faithfulness, retrieval recall, and hallucination detection.[cite:65][cite:68][cite:74][cite:77]

### TruLens and the RAG triad

TruLens foregrounds a three-part evaluation view sometimes called the RAG triad: context relevance, groundedness, and answer relevance. This is conceptually useful even if TruLens is not the final evaluation tool, because it gives a clear vocabulary for discussing failure modes.[cite:65]

### RAGAS and metric-oriented evaluation

RAGAS is commonly discussed as an offline evaluation toolkit for retrieval and answer quality. It is especially helpful for experiments and benchmark-style comparison between configurations.[cite:68][cite:74][cite:77]

### DeepEval and test-like evaluation

DeepEval is often described as making LLM evaluation feel more like unit testing. This framing is valuable for planning because it suggests that some aspects of the project can be validated with repeatable test cases rather than only manual inspection.[cite:68][cite:74]

### Practical implication for the project

A strong side project should probably not try to build a full evaluation framework from scratch. Instead, it can export structured traces and offline evaluation artifacts and then use an existing evaluation toolkit to compare system variants. What matters most is not authorship of the evaluator but rigor in measuring the system.[cite:65][cite:74][cite:77]

## Observability and tracing landscape

As RAG and agent systems mature, observability is increasingly treated as a first-class need rather than an afterthought. LangSmith explicitly positions itself as a framework-agnostic observability and evaluation platform for LLM applications and agent systems, with tracing, monitoring, and deployment support.[cite:66][cite:69] Broader surveys of observability tools also point to W&B Weave, Opik, and other platforms for tracing, cost monitoring, latency analysis, and online evaluation.[cite:72][cite:75][cite:78]

For a side project, observability is valuable for two reasons. First, it gives the project production flavor. Second, it creates evidence for architectural claims. If the project claims lower latency or better retrieval quality, traces and metrics make that claim more credible.

A planning-friendly observability model would track at least:

- End-to-end request latency.
- Time spent in parsing, embedding, retrieval, reranking, and generation.
- Tokens in and tokens out.
- Number of chunks retrieved and passed into context.
- Retrieval scores.
- Failure and retry counts.
- Model/provider used for each step.

This could be exposed through custom logs, OpenTelemetry-style spans, or integration with an existing trace platform.[cite:66][cite:69][cite:72]

## Programming-language and architecture direction landscape

One of the central planning questions in this thread has been whether the whole project should be written in Rust or whether Go should serve as the backend/interface layer while Rust handles the core RAG engine.

### Pure Rust architecture

A pure Rust implementation has obvious appeal for signaling systems capability and type-safety discipline. It keeps the language story simple, reduces cross-service contract management, and can create a very coherent technical identity: a Rust-native RAG engine with strong performance and explicit orchestration.[cite:3][cite:10][cite:56]

The main risks are development speed and project friction. User-facing API iteration, web middleware, and broad ecosystem convenience may move more slowly in Rust than in Go, especially for someone still building Rust fluency.

### Go frontend/backend plus Rust core architecture

A split architecture with Go as the user-facing backend or control plane and Rust as the internal RAG engine or data plane is a strong and realistic pattern. Industry architecture discussions around control plane versus data plane, service mesh design, and AI gateway structure reinforce the idea that different languages can sensibly own different parts of the system, with Go often used for operational or user-facing services and Rust used where data-plane performance and safety matter more.[cite:86][cite:88]

This architecture has several advantages. It lets Go handle HTTP APIs, auth, request shaping, user sessions, and general service ergonomics while Rust focuses on the performance-sensitive retrieval and orchestration core. It also creates a strong discussion point about language trade-offs and boundaries. However, it introduces nontrivial complexity: service-to-service contracts, deployment of multiple services, streaming across boundaries, and potential duplication of state handling.

### Single-service backend in Go or Rust with external components

A middle path is to use one main backend service and push complexity into external databases and APIs. This can make the project more achievable and easier to explain, though it may reduce the strength of the language-design narrative.

### What this means in planning terms

This document intentionally does not force a choice. Instead, it preserves multiple viable architecture patterns so that the final direction can be chosen later based on time, confidence with Rust, and the desired resume narrative.

## Candidate architecture patterns

### Pattern 1: Monolithic Rust RAG service

In this pattern, a single Rust service handles ingestion, storage integration, retrieval, orchestration, and API endpoints. It may expose REST, WebSocket, or gRPC interfaces and directly communicate with the chosen vector store and model providers.[cite:3][cite:56][cite:61]

This pattern is strongest when the goal is to present a single coherent systems artifact. It also minimizes cross-language coordination and can make the implementation easier to reason about once the Rust foundation is stable.

### Pattern 2: Go gateway plus Rust engine

In this pattern, the Go service acts as API gateway, user-facing backend, and possibly authentication/session layer, while the Rust service acts as the internal RAG engine. Communication could happen over gRPC or internal HTTP. This creates a clean separation between interface/control concerns and retrieval/processing concerns.[cite:85][cite:86][cite:88]

This pattern is especially useful if the user-facing side is expected to evolve quickly while the core retrieval engine is optimized more carefully. It also provides a strong “control plane/data plane” discussion point.

### Pattern 3: Rust engine plus thin UI adapter

Here, the main engineering weight remains in Rust, but a lightweight interface layer in another language or framework exists only to provide a convenient UI or web shell. This can preserve the simplicity of a Rust-centered project while reducing friction around frontend serving or product presentation.

### Pattern 4: Framework-assisted prototype evolving into custom engine

This pattern begins with a framework-heavy implementation to prove the product shape and basic data flow, then incrementally replaces key layers such as chunking, retrieval composition, or orchestration with custom implementations. This is a particularly attractive plan for a learner because it reduces the risk of never shipping while still preserving room for deeper engineering later.[cite:3][cite:52][cite:64]

## Areas where existing tools should probably be used

A major theme in this thread has been selective non-reinvention. Some parts of the stack are poor candidates for custom implementation in a side project because the engineering cost is high and the resume payoff is low.

### Vector indexing internals

Implementing approximate nearest-neighbor indexing algorithms from scratch is rarely the best use of effort for this project. Mature vector engines already solve difficult problems around indexing structures, updates, filtering, and performance. Using existing systems such as LanceDB or Qdrant usually demonstrates better judgment than rebuilding ANN internals.[cite:21][cite:51][cite:57]

### Model providers and embeddings infrastructure

Unless local-model operation is itself the main project goal, it is usually more pragmatic to rely on existing embedding and generation providers. The project gains more from thoughtful orchestration and evaluation than from building bespoke model-hosting infrastructure.[cite:3][cite:5][cite:61]

### Full-featured evaluation frameworks

Rebuilding RAGAS, TruLens, or an equivalent evaluation toolkit is unlikely to be a strong use of time. The project can instead emit structured data that those tools or similar workflows can consume.[cite:65][cite:74][cite:77]

### Generic CRUD and auth scaffolding

If the project includes user accounts or session management, there is little resume value in spending large amounts of time on commodity user management logic unless identity itself is part of the architectural story.

## Areas where custom implementation is likely worth it

These are the places where rebuilding or custom-designing key pieces can create real portfolio value.

### Custom chunking engine

A custom chunking engine that supports fixed-size, recursive, and structure-aware strategies is one of the best investments for this side project. It is central to RAG quality, highly discussable in interviews, and concrete enough to benchmark meaningfully.[cite:64][cite:76]

### Hierarchical indexing or retrieval flow

A custom hierarchical retrieval path that first retrieves sections and then drills down into paragraphs or passages could make the project stand out. This area bridges information retrieval and system design without requiring the project to implement a whole database.[cite:64][cite:67]

### Hybrid retrieval composer

A custom retrieval pipeline that combines dense retrieval, sparse retrieval, filtering, deduplication, and configurable score fusion would show strong architectural thinking. It need not be mathematically novel; the value lies in clean abstractions and transparent trade-offs.[cite:64][cite:71][cite:73]

### Small orchestration runtime

Building a compact state-machine-based workflow engine inspired by LangGraph concepts but expressed in Rust types can be an excellent differentiator. It demonstrates that the project author understands what frameworks are abstracting and can rebuild the important part in a controlled way.[cite:52][cite:58]

### Trace and metrics model

A lightweight custom tracing schema for the system is often worth implementing even if metrics are later visualized with external tools. It supports both observability and evaluation.

## Candidate build strategies

### Strategy A: Framework-first, replace later

This strategy uses a framework such as Rig for LLM access and basic RAG plumbing early, then gradually replaces selected components with custom code. It is one of the safest approaches because it gets the system working first and deepens the custom engineering where it matters most later.[cite:3][cite:56][cite:61]

### Strategy B: Core-first, interface later

This strategy starts by building the engine: chunking, retrieval, indexing abstractions, and orchestration. The UI and broad product shell are delayed until the core works well. This is best if the main goal is technical depth and if there is confidence in staying motivated without an early demo.

### Strategy C: Product shell first

This strategy builds the simplest useful user-facing flow first, such as upload documents and ask questions, then fills in evaluation, observability, and retrieval sophistication later. It can be better for accountability and demo value but may tempt the project into staying shallow.

### Strategy D: Comparative experimentation project

This strategy frames the side project partly as a research artifact. The deliverables include not only a working engine but also experiments comparing chunking methods, retrieval strategies, or rerank configurations. This is especially strong for resume value if the resulting report is clear and rigorous.[cite:64][cite:70][cite:74]

## Candidate domain choices

The project can become much stronger if the retrieval problem is tied to a coherent corpus rather than generic uploads.

Possible domains include:

- Technical documentation assistant.
- Codebase assistant for repositories.
- Academic or research paper retrieval assistant.
- Personal knowledge base with memory and notes.
- Observability or incident-response assistant using logs and runbooks.
- Job-search or resume knowledge assistant.
- Data-engineering and infra learning corpus.

A domain-specific corpus tends to improve the project because it supports richer metadata, better chunking logic, more realistic evaluation questions, and more defensible product choices.

## Candidate feature set for an MVP

A realistic minimal version could include:

- Document ingestion for one or two source types.
- One vector store backend.
- One embedding provider.
- At least two chunking strategies.
- Basic retrieval and optional rerank.
- LLM answer generation with source-aware context.
- Logging or tracing of pipeline stages.
- A small evaluation set.
- A CLI or minimal API endpoint.

This is enough to support serious discussion without requiring a full product platform.

## Candidate feature set for a stronger v2

A more ambitious version could additionally include:

- Pluggable storage backends.[cite:21][cite:51][cite:57]
- Hybrid dense plus sparse retrieval.[cite:64][cite:73]
- Multi-stage reranking.[cite:64][cite:70]
- Conversation memory and context budgeting.[cite:28][cite:65]
- A state-machine orchestration runtime inspired by graph-based agent systems.[cite:52][cite:58]
- Streaming responses across service boundaries.
- Offline eval runs with RAGAS or TruLens-style metrics.[cite:65][cite:74][cite:77]
- OpenTelemetry-compatible traces or an integration path to LangSmith or similar tools.[cite:66][cite:69][cite:72]

## Candidate service boundaries and interface contracts

If the architecture is split across services, the interface between layers becomes a major planning concern.

Possible contract styles include:

- Internal REST/HTTP.
- gRPC with Protocol Buffers.
- Async job queue for long-running ingestion tasks.
- Streaming protocol for incremental token output.

A Go-plus-Rust design especially benefits from an explicit contract because it makes ownership boundaries clear. It also gives the project a stronger systems-integration story. On the other hand, a pure Rust design may intentionally avoid this complexity until later.

## Deployment and infrastructure options

The deployment story can range from extremely local to fairly production-like.

### Local-first deployment

This approach uses Docker Compose or even a fully local embedded setup. It is ideal for fast iteration and for keeping the project manageable. LanceDB is especially attractive in such a mode because of its embedded local character.[cite:21][cite:36]

### Multi-container self-hosted deployment

This approach uses separate containers for the API, the RAG engine, the database, and the vector store. It is useful if one of the goals is to demonstrate distributed service composition.

### Managed-service hybrid deployment

This approach keeps the core service self-managed but delegates storage or model hosting to cloud providers. It may be a good compromise if the project wants production flavor without excessive operational overhead.

## Resume positioning options

How the project is described may matter nearly as much as how it is built.

Possible positionings include:

- Built a Rust-native RAG engine with pluggable retrieval backends and evaluation-driven chunking experiments.[cite:21][cite:64]
- Architected a control-plane/data-plane AI system with Go APIs and a Rust retrieval core.[cite:86][cite:88]
- Implemented a configurable hybrid retrieval pipeline with dense and sparse search, reranking, and structured traces.[cite:64][cite:71][cite:73]
- Designed a state-machine-based agent orchestration runtime for grounded document QA inspired by graph-based agent frameworks.[cite:52][cite:58]
- Added rigorous RAG observability and offline evaluation using trace exports and retrieval quality metrics.[cite:65][cite:66][cite:69][cite:74]

These positionings are not mutually exclusive, and the final wording should follow what was actually built.

## Risks and failure modes

There are several ways this kind of project can go wrong, and naming them explicitly helps planning.

One risk is overbreadth. Combining Rust learning, distributed systems, vector search, UI work, evaluation, and multi-agent design can become too large to finish. Another risk is choosing too many novel components at once, which makes debugging hard and progress slow. A third risk is building a product shell with little actual retrieval sophistication, resulting in a polished demo with weak technical depth. A fourth risk is over-indexing on infrastructure complexity, such as too many services or databases, while neglecting answer quality and evaluation.[cite:64][cite:71]

A good planning rule is that each extra dimension of novelty should justify itself. If the project already includes a custom chunker, a custom retrieval composer, and Rust as the main implementation language, then adding multi-agent role systems, Web3 integration, or elaborate deployment topologies may not improve resume value proportionally.

## Planning questions that remain intentionally open

This document does not resolve the following questions, because they depend on personal preference, time budget, and desired positioning:

- Should the project be pure Rust or split between Go and Rust?[cite:86][cite:88]
- Should the vector backend be local-first with LanceDB, service-oriented with Qdrant, or relationally integrated with PostgreSQL plus vector support?[cite:21][cite:51][cite:54][cite:57]
- Should the first version prioritize engine depth, user-facing polish, or comparative experimentation?
- Should the orchestration layer be framework-driven, custom, or hybrid?[cite:3][cite:52][cite:56][cite:61]
- Should evaluation be mostly offline, mostly trace-driven, or both?[cite:65][cite:66][cite:74]
- Should the system be general-purpose or domain-specific?
- Should memory be limited to conversation history, or expanded into more explicit long-term retrieval memory?[cite:28]
- Should reranking be omitted at first, or included early as a differentiator?[cite:64][cite:70]

Leaving these open is a feature, not a weakness. The purpose of this document is to preserve the option space for later brainstorming and technical planning.

## Discussion prompts for further brainstorming

To make this document useful in conversations with other engineers or AI systems, the following prompts can help structure the next round of planning:

- Which two layers of the stack should be custom-built to maximize resume value while keeping scope manageable?
- Which architecture pattern best matches the desired job narrative: infra-heavy, AI-platform, backend-product, or balanced?
- Which storage backend gives the best mix of realism, accessibility, and technical discussion value?
- Is a domain-specific corpus worth the tighter scope if it improves evaluation quality and retrieval design?
- Should the project optimize for local-first reproducibility or for distributed-service realism?
- What is the smallest set of metrics and traces that would make performance and quality claims credible?
- What is the earliest milestone that would make the project demoable even if later experiments are unfinished?
- Which part of the system would be most impressive to explain live in an interview?

## Closing planning stance

The most promising interpretation of the project remains a selective-build end-to-end RAG system: one that uses existing tools for commodity capabilities, but deliberately rebuilds one or more high-leverage layers such as chunking, hybrid retrieval composition, orchestration state management, or trace design. That approach aligns well with current market relevance, preserves room for infra-oriented thinking without requiring a full commitment to database internals, and produces a much stronger discussion artifact than either a pure wrapper project or an overengineered but unfinished platform.[cite:10][cite:25][cite:47][cite:64]

At the same time, no single stack or architecture has been fixed here on purpose. The strongest next step is not immediate implementation, but one more round of narrowing: choose the job narrative to optimize for, choose the smallest version that still demonstrates differentiated engineering, and then map the chosen design into milestones. This document is intended to make that narrowing process easier rather than to replace it.[cite:1][cite:10][cite:64]
