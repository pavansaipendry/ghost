# Pavan Sai Reddy Pendry — Machine Learning Engineer

pavansaipendry2002@gmail.com | (785) 813-7825 | Irving, TX (open to relocation) | pavansaipendry.dev
github.com/pavansaipendry | linkedin.com/in/pavansaireddypendry

## Summary

Machine learning engineer with production experience building and shipping ML systems end to end, from data pipelines and model training to inference serving at scale. Strong across ranking and retrieval systems, reinforcement learning with exploration vs exploitation trade-offs, transformer and foundation model architecture, and rigorous model evaluation. Shipped a production AI assistant serving 7,300+ courses on a multi-stage ranking and retrieval pipeline (35x latency improvement), fine-tuned transformer models on SEC financial filings, and built RL agents that balance exploration and exploitation in dynamic environments. Fluent in Python, SQL, PyTorch, and TensorFlow with a focus on clean, tested, production-ready code. Published researcher (Springer, IEEE). M.S. Computer Science, University of Kansas, May 2026.

## Technical Skills

- **Languages:** Python, SQL, Java, C++, TypeScript, JavaScript (ES6+), Bash
- **ML & Modeling:** PyTorch, TensorFlow, scikit-learn, XGBoost, Hugging Face Transformers, deep learning, CNNs, LSTMs, transformer architecture, foundation models, attention (FlashAttention, PagedAttention, GQA, RoPE), fine-tuning, RLHF/GRPO
- **Ranking, Recsys & RL:** ranking and recommendation systems, learning to rank (LTR), collaborative filtering, content-based filtering, hybrid models, retrieval ranking, reinforcement learning (PPO, reward shaping, Stable-Baselines3, Gymnasium), multi-armed bandits, exploration vs exploitation
- **Experimentation:** A/B testing, statistical analysis, model evaluation (offline & online), Pytest evaluation suites, CI regression checks, human-in-the-loop systems
- **Infra & MLOps:** ML pipelines, data curation (MinHash/LSH dedup), LLM inference serving, KV-cache management, continuous batching, AWS (EC2, Lambda, S3), Docker, Kubernetes, CI/CD (GitHub Actions), vector DBs (Qdrant, ChromaDB, pgvector), Redis, PostgreSQL, Triton/CUDA kernels, A100 GPUs
- **Practices:** distributed systems, system design, code reviews, testing, performance optimization, Agile, Git

## Experience

### Research Software Engineer (Machine Learning) — University of Kansas
Lawrence, KS | Jan 2025 – May 2026
- Built and shipped **BabyJay**, a production AI assistant serving 7,300+ courses and 2,207 faculty, reaching 82.4% user approval through a real-time feedback loop that drove continuous model and prompt iteration and evaluation.
- Engineered a multi-stage **ranking and retrieval pipeline** (preprocessor, classifier, router, 8 specialized retrievers) over ChromaDB and pgvector, cutting average retrieval latency from 500–1000ms to 5–50ms, a **35x improvement** over pure vector search.
- Built a learned classifier and router that prioritizes and routes queries across retrievers, plus automated **Pytest evaluation suites with CI regression checks** to measure retrieval accuracy and guard against regressions.
- Deployed a scalable FastAPI inference backend with JWT auth and a 3-tier rate limiter under a daily inference-cost budget; built 9 production Python data pipelines with retry logic, dedup, and schema validation; mentored 100+ students as a graduate TA.

### Software Engineer Intern — Note
Remote, USA | May 2025 – Aug 2025
- Built a developer-intelligence platform that captures and analyzes LLM coding-agent sessions: 25+ REST endpoints (Next.js 16 App Router) across auth, prompts, projects, search, analytics, and cross-session intelligence.
- Designed a normalized 15-table PostgreSQL schema with tsvector + pg_trgm trigram similarity for fuzzy semantic search, composite indexes, and trigger-driven search vectors; added JWT dual-token auth and a WebSocket + Redis pub/sub layer for real-time session pairing.

### Research Assistant (Machine Learning) — Amrita Vishwa Vidyapeetham
Kerala, India | Jun 2023 – May 2024
- Built **DishKit** using a Bidirectional LSTM (491K params, TensorFlow) for next-word prediction and nutrient analysis on sequential data; co-authored 2 peer-reviewed papers (Springer LNNS ICT4SD 2024, IEEE i-PACT 2023), serving 500+ users.

## Projects

### Deep RL Agent — Exploration vs Exploitation in Dynamic Environments
PyTorch, Stable-Baselines3, Gymnasium, A100
- Designed and trained a **PPO reinforcement learning agent** that optimizes sequential decision-making in a dynamic simulated environment, achieving a 0% collision rate at ~80 km/h across evaluation episodes; trained end to end on a cloud A100 (300K steps, 8 vectorized environments).
- Diagnosed premature convergence from training curves and fixed it by tuning the exploration vs exploitation balance with entropy regularization and reward re-shaping, raising mean episode reward from ~24 to ~63; validated real behavior (crash rate, speed, survival) rather than reward alone to rule out reward hacking.

### Banyan — Source-Grounded Research Assistant with Reranked Hybrid Retrieval
Next.js, TypeScript, Claude, SQLite FTS5, cross-encoder reranker
- Built a citation-grounded QA system on a hybrid retrieval and ranking pipeline: dense vector + BM25 keyword search fused with reciprocal rank fusion (RRF), a cross-encoder reranker, query rewriting, and multi-hop self-ask retrieval.
- Built a reproducible evaluation and benchmarking harness comparing generator models on HotpotQA multi-hop QA, scored by a neutral LLM judge across accuracy, EM/F1, latency, and cost per 100 questions to isolate pipeline contribution from model contribution.

### FinDocAgent — ML on Financial Filings
PyTorch, Hugging Face, LangChain, LangGraph, FastAPI, pgvector
- Fine-tuned a DistilBERT transformer on SEC financial filings to 92% classification accuracy and built a LangGraph multi-agent pipeline (Parser, Retriever, Analyzer) producing cited answers, with LangChain running RAG over a pgvector store.

### NSA-mini — Native Sparse Attention from Scratch
PyTorch, Triton, CUDA, A100
- Reimplemented DeepSeek's Native Sparse Attention (ACL 2025 best paper) from scratch, a three-branch mechanism (compression, top-n block selection, sliding window); wrote custom Triton kernels reaching 22x faster forward vs FlashAttention-2 at 64K context, verified on enwik8 with a 38-test correctness harness.

### mini-vLLM — From-Scratch LLM Inference & Serving Engine
PyTorch, Triton, Qwen2.5
- Built an LLM inference and serving engine from scratch implementing PagedAttention and continuous batching, reproducing the core of vLLM; matched Hugging Face logits to under 5e-4 and delivered 1.77x decode throughput over sequential decoding.

### Reasoning SLM — End-to-End LLM Training Pipeline
PyTorch, RunPod, A100, NumPy
- Engineered an end-to-end training pipeline (data to tokenizer to pretraining): curated a 189M-token corpus with from-scratch MinHash + LSH dedup and quality filters, then trained a 118M-parameter transformer from scratch at ~33% MFU and ~146K tokens/sec on a single A100.

## Hackathons

- **HackKU 2025:** shipped a cloud AI application in 36 hours (Claude API, Python, TypeScript) with automated tests and Agile practices; recognized for most innovative use of AI among 60+ teams.
- **Hack K-State 2025:** shipped a real-time collaborative dashboard (Python backend, WebSocket streaming, React) that automated cross-functional task routing via AI classification.

## Education

**M.S. Computer Science, University of Kansas** — Lawrence, KS | Aug 2024 – May 2026
Coursework: Machine Learning, Algorithms, Distributed Systems, Database Systems, Computer Architecture, Software Engineering

**B.Tech. Computer Science & Engineering, Amrita Vishwa Vidyapeetham** — India | Oct 2020 – May 2024
Coursework: Deep Learning, Data Structures, Algorithms, Operating Systems, Computer Networks, OOP, Cloud Computing
