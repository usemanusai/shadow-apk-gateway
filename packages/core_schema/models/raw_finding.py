"""RawStaticFinding — Layer 2 output schema.

Each parser emits a list of these findings. They are unmerged and unscored,
representing a single observation of a potential API endpoint or network interaction.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RawStaticFinding(BaseModel):
    """A single static analysis observation from a parser module.

    These findings are later merged and scored by the trace-model package.
    """

    model_config = ConfigDict(populate_by_name=True)

    finding_id: str = Field(description="UUID for this finding")
    parser_name: str = Field(description="Name of the parser that produced this finding")
    source_file: str = Field(description="Path to the source file where the finding was located")
    line_number: Optional[int] = Field(default=None, description="Line number in the source file")

    # Extracted endpoint data
    method: Optional[str] = Field(
        default=None,
        description="HTTP method (GET, POST, etc.), None if unknown",
    )
    url_path: Optional[str] = Field(
        default=None,
        description="URL path or full URL extracted from the source",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Base URL if separately identified",
    )

    # Parameter information
    parameters: list[ParameterFinding] = Field(default_factory=list)

    # Additional context
    class_name: Optional[str] = Field(default=None, description="Enclosing class name")
    method_name: Optional[str] = Field(default=None, description="Enclosing method name")
    annotation_type: Optional[str] = Field(
        default=None,
        description="Type of annotation or pattern matched (e.g., '@GET', 'OkHttp.Builder')",
    )

    # Confidence qualifiers
    is_dynamic_url: bool = Field(
        default=False,
        description="True if the URL contains string concatenation or dynamic construction",
    )
    has_obfuscated_names: bool = Field(
        default=False,
        description="True if class/method names appear obfuscated",
    )

    raw_context: Optional[str] = Field(
        default=None,
        description="Raw context lines around the finding (for review)",
    )


class ParameterFinding(BaseModel):
    """Parameter extracted from static analysis."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    location: Literal["path", "query", "header", "body", "cookie", "unknown"] = "unknown"
    type_hint: Optional[str] = None
    annotation: Optional[str] = None  # e.g., "@Query", "@Path", "@Header"


# Fix forward reference — ParameterFinding is used by RawStaticFinding
RawStaticFinding.model_rebuild()
