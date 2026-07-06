# Pavan Sai Reddy Pendry — Machine Learning Engineer

pavansaipendry2002@gmail.com | (785) 813-7825 | Irving, TX
pavansaipendry.dev | github.com/pavansaipendry | linkedin.com/in/pavansaireddypendry

## PROFILE

Machine learning engineer specializing in LLM systems and GPU / ML infrastructure. Reimplemented DeepSeek's Native Sparse Attention from scratch in Triton/CUDA (22x faster window kernel at 64K context, A100-validated), built a from-scratch LLM inference engine (PagedAttention + continuous batching), an end-to-end LLM training pipeline (data → tokenizer → pretraining), and ChemExtract, a vision-LLM document extraction system hitting 99.8% flag recall on a 1,082-field eval. Also shipped BabyJay (82.4% user approval, 7,300+ courses) on a multi-stage RAG pipeline. Strong in Python, PyTorch, Triton, TensorFlow, and scikit-learn, with a focus on clean, efficient, well-tested code. Published researcher (Springer, IEEE). M.S. in Computer Science, University of Kansas, May 2026.

## TECHNICAL SKILLS

- **Languages:** Python, Java, C++, TypeScript, JavaScript (ES6+), SQL, Bash
- **Machine Learning & AI:** PyTorch, TensorFlow, scikit-learn, Keras, NumPy, Pandas, Hugging Face Transformers, deep learning, CNNs, LSTMs, LLM architecture & pretraining, attention mechanisms (FlashAttention, PagedAttention, GQA, RoPE, SwiGLU), Triton/CUDA GPU kernels, online softmax, mixed precision (bf16/fp32), vision LLMs, structured outputs (Pydantic), RAG, LangChain, LangGraph, multi-agent systems, model fine-tuning, RLHF/GRPO, BPE tokenization, reinforcement learning (PPO, reward shaping, Stable-Baselines3, Gymnasium), model evaluation, human-in-the-loop systems
- **ML Infrastructure & MLOps:** LLM inference serving, KV-cache management, continuous batching, ML pipelines, data curation (MinHash/LSH dedup), AWS (EC2, Lambda, S3), RunPod, A100 GPUs, Docker, Kubernetes, CI/CD (GitHub Actions), Pytest, kernel profiling & benchmarking, MFU, vector databases (Qdrant, ChromaDB, pgvector), Redis, PostgreSQL, monitoring
- **Practices:** distributed systems, system design, code reviews, testing, numerical debugging, performance optimization, Agile, version control (Git)

## EXPERIENCE

### Research Software Engineer (Machine Learning) | University of Kansas | Lawrence, KS | Jan 2025 – May 2026
- Built BabyJay (babyjay.bot), a production AI campus assistant serving 7,300+ courses and 2,207 faculty through Claude, achieving 82.4% user approval via a real-time feedback loop that drove model and prompt optimization.
- Engineered a multi-stage RAG pipeline (preprocessor, classifier, router, 8 specialized retrievers) over ChromaDB and pgvector, optimizing average retrieval latency from 500-1000ms to 5-50ms, a 35x improvement over pure vector search.
- Built automated Pytest evaluation suites for retrieval accuracy with CI regression checks, and deployed a scalable FastAPI inference backend with JWT auth and a 3-tier rate limiter capped at a daily inference cost budget.
- Built 9 production Python data pipelines with retry logic, deduplication, and schema validation to feed the ML system's knowledge base; mentored 100+ students as a graduate teaching assistant.

### Software Engineer Intern | Note | USA (Remote) | May 2025 – Aug 2025
- Built Note, a developer-intelligence platform capturing and analyzing Claude Code (LLM coding-agent) sessions, designing 25+ REST API endpoints in Next.js 16 App Router covering auth, prompts, projects, search, analytics, and cross-session intelligence features.
- Designed a normalized 15-table PostgreSQL schema (prompts, sessions, projects, knowledge graph, audit log) using tsvector with pg_trgm trigram similarity for fuzzy semantic search, composite indexes, and auto-updating search vectors via triggers.
- Built a WebSocket server with Redis pub/sub for real-time CLI-to-web session pairing using hashed 6-digit codes, plus JWT dual-token auth (7d access, 30d refresh) with bcrypt, token revocation, and rate limiting.
- Built a Node.js CLI with 24 commands (save, search, standup, report, capture, knowledge, share) and a 14-view React 19 dashboard for browsing sessions, prompts, and analytics.

### Research Assistant (Machine Learning) | Amrita Vishwa Vidyapeetham | Kerala, India | Jun 2023 – May 2024
- Built DishKit, integrating a Bidirectional LSTM (491K parameters, TensorFlow) for next-word prediction and nutrient analysis; co-authored 2 peer-reviewed papers (Springer LNNS ICT4SD 2024, IEEE i-PACT 2023), serving 500+ users.

## PROJECTS

### NSA-mini: Native Sparse Attention from Scratch | PyTorch, Triton, CUDA, A100
- Reimplemented DeepSeek's Native Sparse Attention (ACL 2025 best paper) from scratch in PyTorch and Triton: a three-branch mechanism (compression, top-n block selection, sliding window) with GQA-shared block selection and learned per-head gates.
- Wrote custom Triton GPU kernels (FlashAttention-2-style online softmax, group-centric sparse gather) reaching 22x faster forward vs FlashAttention-2 on the window kernel at 64K context with linear scaling and lower peak memory (A100 80GB); verified quality parity on enwik8 (2.164 vs 2.163 bpc) with a 38-test correctness harness.

### mini-vLLM: From-Scratch LLM Inference & Serving Engine | Python, PyTorch, Triton, Hugging Face, Qwen2.5
- Built an LLM inference engine from scratch implementing PagedAttention (block-pooled KV cache, 16-token blocks) and continuous batching (iteration-level scheduling), reproducing the core of vLLM; reimplemented the Qwen2.5 transformer (RMSNorm, RoPE, GQA, SwiGLU), matching Hugging Face logits to under 5e-4.
- Designed a paged KV-cache allocator with per-step block recycling and an admit/decode/evict scheduler delivering 1.77x throughput over sequential decoding (token-for-token verified); profiled the decode path as launch-bound and scaffolded a fused Triton paged-attention kernel validated to 7e-4 vs a dense ground truth.

### ChemExtract: Trust-First Vision-LLM Document Extraction | Python, Claude API (vision), Pydantic, FastAPI, ChromaDB, sentence-transformers, PyMuPDF
- Built a trust-first extraction pipeline for chemistry documents (images, PDFs) on a flag-don't-guess design: N-pass vision extraction with schema-enforced structured outputs, cross-run self-consistency checks, and a deterministic validation layer (unit whitelists, physical-plausibility ranges for 25+ quantity types), achieving 99.8% flag recall and 100% accuracy on unflagged fields over a 200-image, 1,082-field eval at ~$0.10/page.
- Designed a separate LLM inference layer proposing missing units with calibrated confidence and chemistry-grounded reasoning without ever overwriting raw extractions, plus a human-in-the-loop review UI (FastAPI, NDJSON streaming) resolving ambiguities into finalized documents indexed for citation-grounded RAG Q&A (ChromaDB, local embeddings) that refuses off-document questions.

### Reasoning SLM: End-to-End LLM Training Pipeline | PyTorch, RunPod, A100, NumPy
- Engineered an end-to-end LLM training pipeline (data → tokenizer → pretraining) for a math/code reasoning model: curated a 189M-token corpus from multi-source Hugging Face streams with from-scratch MinHash + LSH near-duplicate detection (NumPy) and Gopher-style quality filters.
- Trained a 118M-parameter decoder transformer from scratch with a custom gated-attention block (NeurIPS 2025 repro) at ~33% MFU and ~146K tokens/sec on a single A100 (bf16, gradient accumulation to 262K tokens/step); automated A100 provisioning via the RunPod REST API and trained a 32K-vocab byte-level BPE tokenizer.

### Deep RL Self-Driving Agent (Highway Simulation) | Python, PyTorch, Stable-Baselines3, Gymnasium, TensorBoard, A100
- Built a PPO agent that learns to drive in simulated highway traffic from symbolic observations, achieving a 0% collision rate at ~80 km/h over evaluation episodes; trained end-to-end on a cloud A100 (300K steps, 8 vectorized environments) with best-model checkpointing and live driving-video monitoring in TensorBoard.
- Diagnosed premature convergence from training curves and fixed it with entropy regularization and reward re-shaping, raising mean episode reward from ~24 to ~63 and survival from 24 to 80 steps; validated behavior (crash rate, speed, survival), not reward alone, confirming the agent drives fast and safe rather than reward-hacking.

### FinDocAgent | Python, PyTorch, Hugging Face, LangChain, LangGraph, FastAPI
- Fine-tuned DistilBERT on SEC filings (92% accuracy) and built a LangGraph multi-agent pipeline (Parser, Retriever, Analyzer) producing cited answers, with LangChain handling RAG over a pgvector store.

## HACKATHONS
- **HackKU 2025 (Apr 2025):** Built and shipped a cloud-based AI-powered application in 36 hours using Claude API, Python, and TypeScript with clean code, automated tests, and Agile practices, earning recognition for the most innovative use of AI among 60+ competing teams.
- **Hack K-State 2025 (Oct 2025):** Shipped a real-time collaborative dashboard with Python back-end, WebSocket streaming, and React front-end that automated cross-functional team task routing using AI classification.

## EDUCATION
- **M.S. Computer Science** | University of Kansas | Lawrence, KS | Aug 2024 – May 2026 | Coursework: Machine Learning, Algorithms, Distributed Systems, Database Systems, Computer Architecture, Software Engineering
- **B.Tech. Computer Science and Engineering** | Amrita Vishwa Vidyapeetham, India | Oct 2020 – May 2024 | Coursework: Deep Learning, Data Structures, Algorithms, Operating Systems, Computer Networks, OOP, Cloud Computing
