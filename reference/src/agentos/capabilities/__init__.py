"""Built-in capabilities registry."""
from ..registry import CapabilityManifest
from .search import search
from .llm import llm
from .review import review
from .report import report

CAPABILITIES = {
    "search": search,
    "llm": llm,
    "gather": review,
    "review": review,
    "report": report,
}

CAPABILITY_MANIFESTS = [
    CapabilityManifest(
        task_type="search", display_name="Web Search",
        description="Search the web for information",
        version="0.1.0", tags=["research", "fetch"], fn=search,
    ),
    CapabilityManifest(
        task_type="llm", display_name="LLM Analysis",
        description="Analyze data using a large language model",
        version="0.1.0", tags=["analysis", "ai"], fn=llm,
    ),
    CapabilityManifest(
        task_type="gather", display_name="Result Gathering",
        description="Aggregate and summarize task outputs",
        version="0.1.0", tags=["aggregation"], fn=review,
    ),
    CapabilityManifest(
        task_type="review", display_name="Quality Review",
        description="Review task outputs for quality and completeness",
        version="0.1.0", tags=["quality"], fn=review,
    ),
    CapabilityManifest(
        task_type="report", display_name="Report Generation",
        description="Compile final Markdown report",
        version="0.1.0", tags=["output"], fn=report,
    ),
]

__all__ = ["search", "llm", "review", "report", "CAPABILITIES", "CAPABILITY_MANIFESTS"]
