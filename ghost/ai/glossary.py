"""Domain vocabulary + transcript correction for Ghost STT.

Two problems this solves, both seen in real sessions:

  1. The recognizer never even *knows* a term is likely. Ghost's resume-harvested
     vocabulary only contains what's literally written in the resume - so a common
     interviewer word like "Spark" (absent from the resume) got zero help and came
     out "transparc". The curated TECH_GLOSSARY below covers the tools interviewers
     actually say, independent of what's in the resume.

  2. Different engines bias differently. Whisper/mlx-whisper accept an
     `initial_prompt` (a strong decode-time bias) - as_whisper_prompt() formats the
     glossary for it. Parakeet (TDT/RNNT) has NO prompt-conditioning API, so for that
     path we lean on (a) its higher base accuracy and (b) correct_transcript(), a
     conservative post-hoc fixer that maps close near-misses ("kafgka" -> "Kafka",
     "air flow" -> "Airflow") back to the canonical term. Fully local, deterministic.

Nothing here touches the network - these are on-device recognition hints and a
string-similarity pass, consistent with Ghost's stealth model.
"""

import difflib
import re


# ── Curated technical vocabulary ────────────────────────────────────────────
# The tools/terms an interviewer is likely to *say* in a data-engineering / ML /
# backend interview. Deliberately broad because it's used as a bias + correction
# target, not read aloud. Canonical casing matters: it's what a correction emits.
TECH_GLOSSARY = [
    # Big data / data engineering
    "Spark", "Spark SQL", "PySpark", "Hadoop", "HDFS", "MapReduce", "Hive", "Presto",
    "Trino", "Flink", "Kafka", "Kafka Streams", "Pulsar", "Storm", "Beam", "Airflow",
    "Dagster", "Prefect", "Luigi", "dbt", "Snowflake", "Databricks", "Redshift",
    "BigQuery", "Athena", "Glue", "EMR", "Delta Lake", "Iceberg", "Hudi", "Parquet",
    "Avro", "ORC", "Protobuf", "Arrow", "Dremio", "Fivetran", "Airbyte", "Debezium",
    "ETL", "ELT", "CDC", "OLAP", "OLTP", "data lake", "lakehouse", "data warehouse",
    "star schema", "partitioning", "bucketing", "denormalization", "backfill",
    # Databases / storage
    "PostgreSQL", "Postgres", "MySQL", "SQLite", "MongoDB", "Cassandra", "ScyllaDB",
    "DynamoDB", "Redis", "Memcached", "Elasticsearch", "OpenSearch", "Neo4j",
    "CockroachDB", "ClickHouse", "DuckDB", "TimescaleDB", "InfluxDB", "Pinecone",
    "Weaviate", "Milvus", "pgvector", "Qdrant", "Chroma", "sharding", "replication",
    # Cloud / infra / orchestration
    "AWS", "GCP", "Azure", "S3", "EC2", "Lambda", "ECS", "EKS", "GKE", "Fargate",
    "Kubernetes", "Docker", "Terraform", "Ansible", "Helm", "Pulumi", "Jenkins",
    "GitHub Actions", "GitLab", "ArgoCD", "Prometheus", "Grafana", "Datadog",
    "CloudWatch", "PagerDuty", "Kinesis", "SQS", "SNS", "Pub/Sub", "Cloud Functions",
    # ML / DS
    "PyTorch", "TensorFlow", "Keras", "JAX", "scikit-learn", "XGBoost", "LightGBM",
    "CatBoost", "Pandas", "NumPy", "SciPy", "Matplotlib", "Hugging Face",
    "Transformers", "LangChain", "LlamaIndex", "MLflow", "Weights & Biases",
    "Kubeflow", "SageMaker", "Vertex AI", "ONNX", "CUDA", "cuDNN", "Triton",
    "embeddings", "fine-tuning", "quantization", "inference", "gradient descent",
    "backpropagation", "overfitting", "regularization", "hyperparameter",
    "cross-validation", "feature engineering", "feature store", "Feast",
    # ML/AI acronyms
    "LLM", "RAG", "RLHF", "GAN", "CNN", "RNN", "LSTM", "GRU", "BERT", "GPT", "MLP",
    "SVM", "KNN", "PCA", "NLP", "OCR", "MLOps", "GPU", "TPU", "vector database",
    # Backend / systems / general SWE
    "REST", "GraphQL", "gRPC", "WebSocket", "OAuth", "JWT", "Nginx", "Envoy",
    "microservices", "monolith", "message queue", "idempotency", "eventual consistency",
    "load balancer", "rate limiting", "caching", "throughput", "latency", "concurrency",
    "multithreading", "async", "coroutine", "mutex", "deadlock", "CAP theorem",
    "ACID", "BASE", "two-phase commit", "consensus", "Raft", "Paxos", "quorum",
    # Languages / runtimes
    "Python", "Java", "Scala", "Golang", "Rust", "TypeScript", "JavaScript",
    "C++", "Kotlin", "SQL", "Bash", "GraphQL", "JVM",
    # Data-structures / CS interview words
    "algorithm", "binary search", "hash map", "hash table", "linked list",
    "binary tree", "heap", "graph", "dynamic programming", "recursion",
    "big O", "time complexity", "space complexity", "two pointer", "sliding window",
    "breadth-first", "depth-first", "topological sort", "Dijkstra", "memoization",
    "LeetCode", "HackerRank",
]


def _clean(term: str) -> str:
    return term.strip(" .,:;()[]{}\"'`").strip()


def build_glossary(context_terms=None, extra=None, max_terms: int = 400) -> list:
    """Merge the curated glossary with resume-harvested `context_terms` (and any
    `extra`), deduped case-insensitively, curated terms first. Returned list is the
    single source of truth passed to every biasing/correction consumer."""
    out, seen = [], set()

    def add(t):
        t = _clean(t)
        if len(t) < 2:
            return
        k = t.lower()
        if k in seen:
            return
        seen.add(k)
        out.append(t)

    for t in TECH_GLOSSARY:
        add(t)
    for t in (context_terms or []):
        add(t)
    for t in (extra or []):
        add(t)
    return out[:max_terms]


def as_whisper_prompt(glossary: list, max_chars: int = 900) -> str:
    """Format the glossary as a Whisper `initial_prompt`. A comma-separated vocab
    list is the established way to bias Whisper toward domain terms. Capped because an
    over-long prompt eats the decoder's context and can itself cause hallucination."""
    if not glossary:
        return ""
    prompt, terms = "Glossary: ", []
    for t in glossary:
        candidate = ", ".join(terms + [t])
        if len(prompt) + len(candidate) > max_chars:
            break
        terms.append(t)
    return prompt + ", ".join(terms) + "."


# ── Post-transcription correction (engine-agnostic, used for Parakeet) ───────

# Explicit phonetic fixes for splits/mangles too far apart for fuzzy ratio to catch
# (multi-word mishears where the recognizer inserted a space or wrong syllables).
_PHONETIC_FIXES = {
    "pie torch": "PyTorch", "pi torch": "PyTorch", "python torch": "PyTorch",
    "tensor flow": "TensorFlow", "tensorflow": "TensorFlow",
    "psychic learn": "scikit-learn", "sci kit learn": "scikit-learn",
    "cyclic learn": "scikit-learn", "scikit learn": "scikit-learn",
    "cube flow": "Kubeflow", "cuban eddies": "Kubernetes", "cube kernetes": "Kubernetes",
    "cuber netes": "Kubernetes", "kubernetis": "Kubernetes",
    "air flow": "Airflow", "data bricks": "Databricks", "snow flake": "Snowflake",
    "big query": "BigQuery", "elastic search": "Elasticsearch",
    "post gres": "Postgres", "postgre s": "Postgres", "dynamo db": "DynamoDB",
    "mongo db": "MongoDB", "d b t": "dbt", "e t l": "ETL", "e l t": "ELT",
    "graph q l": "GraphQL", "rest api": "REST API", "lead code": "LeetCode",
    "leet code": "LeetCode", "hugging face": "Hugging Face",
    "lang chain": "LangChain", "spark sql": "Spark SQL", "pi spark": "PySpark",
    "py spark": "PySpark", "map reduce": "MapReduce",
}

# Common English words that happen to be near a glossary term - never "correct" these.
_PROTECT = {
    "spark", "hive", "storm", "beam", "arrow", "glue", "athena", "presto", "keras",
    "java", "rust", "python", "scala", "go", "heap", "graph", "hash", "cache", "async",
    "the", "and", "for", "with", "data", "queue", "star", "delta", "lake",
}


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def correct_transcript(text: str, glossary: list, threshold: float = 0.86) -> str:
    """Conservatively map near-miss words back to canonical glossary terms.

    Two passes: (1) explicit multi-word phonetic fixes; (2) per-token fuzzy match
    against single-word glossary terms. Deliberately cautious - a wrong "correction"
    is worse than leaving a mishear alone, so we require a high similarity ratio, skip
    short tokens, and never touch a token that's already a real word/glossary term.
    """
    if not text or not glossary:
        return text

    low = text.lower()
    for wrong, right in _PHONETIC_FIXES.items():
        if wrong in low:
            text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
            low = text.lower()

    # Single-word glossary targets, indexed by normalized form for exact-skip.
    singles = [g for g in glossary if " " not in g and "-" not in g and len(g) >= 4]
    norm_set = {_norm(g) for g in glossary}

    def fix_token(tok: str) -> str:
        core = _norm(tok)
        if len(core) < 4 or core in norm_set or core in _PROTECT:
            return tok  # already valid / protected / too short to match safely
        best = difflib.get_close_matches(core, [_norm(s) for s in singles],
                                         n=1, cutoff=threshold)
        if not best:
            return tok
        canon = next(s for s in singles if _norm(s) == best[0])
        # Preserve trailing punctuation on the original token.
        trail = re.sub(r"^[\w'-]*", "", tok)
        return canon + trail

    return re.sub(r"[A-Za-z][\w'-]*", lambda m: fix_token(m.group(0)), text)
