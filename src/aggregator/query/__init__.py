"""Query expansion: free text -> `ExpandedQuery` (LLM, cached, with a rule-based fallback)."""

from aggregator.query.fallback import expand_with_rules
from aggregator.query.llm import AnthropicExpander, LLMExpansionError
from aggregator.query.normalize import clean_expansion, normalize_input
from aggregator.query.service import LLMExpander, QueryExpander, build_query_expander
from aggregator.query.store import DbExpansionStore, ExpansionStore, InMemoryExpansionStore

__all__ = [
    "AnthropicExpander",
    "DbExpansionStore",
    "ExpansionStore",
    "InMemoryExpansionStore",
    "LLMExpander",
    "LLMExpansionError",
    "QueryExpander",
    "build_query_expander",
    "clean_expansion",
    "expand_with_rules",
    "normalize_input",
]
