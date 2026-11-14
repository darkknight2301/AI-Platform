"""All prompt text and JSON schemas in one place. Bump PROMPT_VERSION when editing prompts."""

PROMPT_VERSION = "1"

# key -> (title, guidance given to the model)
SECTIONS: dict[str, tuple[str, str]] = {
    "background": ("Background", "why the work exists; business and technical context"),
    "requirements": ("Requirements", "what must be delivered; acceptance criteria"),
    "discussion_history": ("Discussion history", "key points of the conversation, oldest first"),
    "technical_approach": ("Technical approach", "design/solution approach discussed or chosen"),
    "decisions": ("Decisions", "decisions that were explicitly made, and by whom"),
    "implementation": ("Implementation details", "what was changed; MRs, branches, commits"),
    "dependencies": ("Dependencies", "other tickets, teams, systems or releases this depends on"),
    "blockers": ("Blockers", "what currently prevents progress"),
    "unresolved_questions": ("Unresolved questions", "open questions nobody has answered"),
    "contradictions": ("Contradictions and outdated information",
                       "statements that conflict or were superseded; cite BOTH sides"),
    "requirement_changes": ("Requirement changes", "requirements that changed during the discussion"),
    "current_status": ("Current status", "where the work stands now"),
}
RISK_SECTIONS = ("blockers", "unresolved_questions", "contradictions", "requirement_changes")

_CLAIM = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "basis": {"type": "string", "enum": ["confirmed", "assumption"]},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "basis", "sources"],
}
SECTION_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "array", "items": _CLAIM} for k in SECTIONS},
    "required": list(SECTIONS),
}

_RULES = """You are a precise engineering analyst summarising Redmine tickets.
Rules:
1. Use ONLY the material provided. If something is missing, say "Not available in ticket data". Never guess.
2. Every statement has a basis. "confirmed" = stated explicitly in the material (sources required).
   "assumption" = your inference; say in the text why you infer it.
3. Cite sources with the tags exactly as they appear in the material, e.g. "#1234" or "#1234 J56". Never invent tags.
4. Never write a ticket number, merge request, branch or commit that is not in FACTS or the material.
5. Later comments supersede earlier ones. When statements conflict, or a requirement changed, report both sides
   with both tags under "contradictions" / "requirement_changes".
6. Text marked [translated from Japanese] is machine translation; [UNTRANSLATED JAPANESE] could not be translated.
7. Be concise and do not repeat yourself across sections."""

SYSTEM_JSON = _RULES + "\n8. Reply with a single JSON object matching the schema, nothing else. Use [] for empty sections."
SYSTEM_TEXT = _RULES + "\n8. Reply in plain text only: no markdown, no bullet points, no headings."

_GUIDE = "\n".join(f'- "{k}": {guide}' for k, (_, guide) in SECTIONS.items())


def ticket_prompt(material: str, facts: str, part: str = "") -> str:
    """Pass 1: analyse a single ticket (``part`` notes when its history is split in chunks)."""
    return f"""TASK: Analyse this single Redmine ticket{part}. Fill every section; use [] when the material says nothing.
SECTIONS:
{_GUIDE}

FACTS (extracted by code; the only identifiers you may mention):
{facts}

TICKET MATERIAL:
{material}"""


def consolidate_prompt(root_id: int, facts: str, material: str) -> str:
    """Pass 2: one consolidated analysis of the root ticket and everything related to it."""
    return f"""TASK: Produce ONE consolidated analysis of root ticket #{root_id} together with its parent, sub-tasks and related tickets.
Treat them as a single body of work: merge overlaps, say each thing once, and cite the ticket each statement comes from.
SECTIONS:
{_GUIDE}

FACTS (extracted by code; the only identifiers you may mention):
{facts}

MATERIAL:
{material}"""


def summary_prompt(root_id: int, analysis: str) -> str:
    """Pass 3: 3-5 sentence summary based only on the consolidated analysis."""
    return f"""TASK: Write a short summary of ticket #{root_id} in 3 to 5 sentences covering the objective, the current situation and the outcome (or say the outcome is not yet known).
Use only the ANALYSIS below. Mark assumptions as such. Mention ticket numbers like #1234 where useful.

ANALYSIS:
{analysis}"""


def repair_prompt(prompt: str, error: str) -> str:
    """Retry prompt after invalid JSON: same task, with the parser error and a brevity hint."""
    return f"{prompt}\n\nYour previous reply was not valid JSON ({error}). Reply again with ONLY the JSON object and keep each statement short."
