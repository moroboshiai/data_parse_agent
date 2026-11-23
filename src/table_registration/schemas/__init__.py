"""结构化输出模型。"""

from table_registration.schemas.candidate_rule import CandidateDocument, CandidateMapping
from table_registration.schemas.mapping_result import FieldMapping, MappingBatch, NormalizedSourceSchema
from table_registration.schemas.quality_result import CleaningRuleDraft, ExtractionRuleDraft, FieldQuality

__all__ = [
    "CandidateDocument",
    "CandidateMapping",
    "CleaningRuleDraft",
    "ExtractionRuleDraft",
    "FieldMapping",
    "FieldQuality",
    "MappingBatch",
    "NormalizedSourceSchema",
]
