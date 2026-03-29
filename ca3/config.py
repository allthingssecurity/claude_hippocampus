"""Configuration constants for CA3 associative memory."""

import os

# Neo4j connection (same instance as contextgraph)
NEO4J_URL = os.environ.get("TRACE_NEO4J_URL", "http://localhost:7475")
NEO4J_AUTH = os.environ.get("TRACE_NEO4J_AUTH", "neo4j:${NEO4J_PASSWORD:-changeme}")
GRAPHITI_URL = os.environ.get("TRACE_GRAPHITI_URL", "http://localhost:8100")
GROUP_ID = os.environ.get("TRACE_GROUP_ID", "claude-traces")

# Co-activation parameters
RECENCY_LAMBDA = 0.03  # Decay rate: half-life ~23 days
MIN_COOCCURRENCE = 1  # Minimum co-occurrences to create edge

# Spreading activation parameters
MAX_SEEDS = 7
MAX_SPREAD_HOPS = 2  # Upgraded to 2-hop
SPREAD_DECAY = 0.3  # Tighter decay to reduce noise on distant hops
ACTIVATION_THRESHOLD = 0.15  # Raised from 0.1 to filter weak activations
MIN_COACTIVATION_WEIGHT = 1.0  # Raised from 0.3 — require solid co-occurrence
MAX_NEIGHBORS_PER_HOP = 20  # Reduced from 30 to focus on strongest edges
MAX_ACTIVATED = 15  # Reduced from 20 to keep packets focused

# Context packet
CONTEXT_PACKET_MAX_TOKENS = 1200  # Tighter budget for cleaner packets
TOKEN_ESTIMATE_DIVISOR = 4  # ~4 chars per token

# Entity name filters — skip entities whose names match these patterns
# (file paths, URLs, UUIDs, and overly long names are noise)
ENTITY_NAME_MAX_LEN = 80
ENTITY_NAME_SKIP_PREFIXES = ("/Users/", "/tmp/", "/private/", "/var/", "http://", "https://", "/workspace/")

# Stopwords for keyword extraction from cues
STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out", "off",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "both", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "because", "but", "and",
    "or", "if", "while", "about", "this", "that", "these", "those", "it",
    "its", "i", "me", "my", "we", "our", "you", "your", "he", "him",
    "his", "she", "her", "they", "them", "what", "which", "who", "whom",
    "please", "help", "want", "need", "like", "also", "get", "make",
    "know", "think", "see", "look", "use", "try", "tell", "give", "go",
    "run", "let", "keep", "set", "put", "add", "take", "new", "file",
    "code", "using", "work", "working", "thing", "way",
})
