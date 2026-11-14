"""Catalogue of analysis sections: report titles and the guidance given to the model."""

from dataclasses import dataclass

from .models import Section


@dataclass(frozen=True)
class SectionInfo:
    """Presentation and prompting metadata of one section."""

    title: str
    guidance: str
    is_risk: bool = False  # risk sections are highlighted and listed as "open issues"


SECTION_INFO: dict[Section, SectionInfo] = {
    Section.BACKGROUND: SectionInfo("Background", "why the work exists; business and technical context"),
    Section.REQUIREMENTS: SectionInfo("Requirements", "what must be delivered; acceptance criteria"),
    Section.DISCUSSION_HISTORY: SectionInfo("Discussion history", "key points of the conversation, oldest first"),
    Section.TECHNICAL_APPROACH: SectionInfo("Technical approach", "design/solution approach discussed or chosen"),
    Section.DECISIONS: SectionInfo("Decisions", "decisions that were explicitly made, and by whom"),
    Section.IMPLEMENTATION: SectionInfo("Implementation details", "what was changed; MRs, branches, commits"),
    Section.DEPENDENCIES: SectionInfo("Dependencies", "other tickets, teams, systems or releases this depends on"),
    Section.BLOCKERS: SectionInfo("Blockers", "what currently prevents progress", is_risk=True),
    Section.UNRESOLVED_QUESTIONS: SectionInfo(
        "Unresolved questions", "open questions nobody has answered", is_risk=True
    ),
    Section.CONTRADICTIONS: SectionInfo(
        "Contradictions and outdated information",
        "statements that conflict or were superseded; cite BOTH sides",
        is_risk=True,
    ),
    Section.REQUIREMENT_CHANGES: SectionInfo(
        "Requirement changes", "requirements that changed during the discussion", is_risk=True
    ),
    Section.CURRENT_STATUS: SectionInfo("Current status", "where the work stands now"),
}

RISK_SECTIONS: tuple[Section, ...] = tuple(s for s, info in SECTION_INFO.items() if info.is_risk)
