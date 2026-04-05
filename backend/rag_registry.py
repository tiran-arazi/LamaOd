"""RAG document chunks: embedding text and route labels per dataset.

Add registrations here and call ``register_rag_layers`` from app startup.
To index ArcGIS catalog layers later, loop ``CatalogIndex`` and ``rag.register(...)``.
"""

from __future__ import annotations

from catalog_rag import CatalogRAG

TNUFA_RAG_DESCRIPTION_EN = (
    "Layer: Tnufa injury events by city. "
    "Domain: injury counts, casualties, wounded persons per city in Israel. "
    "Fields: City (Hebrew city name), MinorInjuries, ModerateInjuries, "
    "SeriousInjuries, SevereInjuries. "
    "Topics: injuries, wounded, casualties, city statistics, how many injured."
)

TNUFA_RAG_DESCRIPTION_HE = (
    "שכבה: תנופה אירועי פציעה לפי עיר. "
    "תחום: ספירת פצועים, נפגעים, נפצעים לפי ערים בישראל. "
    "שדות: עיר, פצועים קל, פצועים בינוני, פצועים קשה, פצועים אנוש. "
    "נושאים: כמה פצועים, נפגעים לפי עיר, סטטיסטיקה של פציעות, תנופה."
)


def register_rag_layers(rag: CatalogRAG) -> None:
    """Register all curated chunks before ``CatalogRAG.embed``."""
    rag.register(TNUFA_RAG_DESCRIPTION_EN, route_label="tnufa")
    rag.register(TNUFA_RAG_DESCRIPTION_HE, route_label="tnufa")
