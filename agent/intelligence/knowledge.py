"""Build With Abdallah knowledge base loader."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"


@dataclass
class ExpertiseArea:
    name: str
    aliases: list[str]
    weight: int


@dataclass
class BWAProject:
    name: str
    slug: str
    description: str
    topics: list[str]
    weight: int
    urls: list[str]
    repo: str | None = None


@dataclass
class StackItem:
    name: str
    aliases: list[str]
    weight: int


@dataclass
class ContentRule:
    id: str
    description: str
    weight: int
    keywords: list[str] = field(default_factory=list)


@dataclass
class KnowledgeBase:
    expertise: list[ExpertiseArea]
    projects: list[BWAProject]
    stack: list[StackItem]
    rules: list[ContentRule]

    def all_aliases(self) -> dict[str, tuple[str, int]]:
        """Map every alias to (category_name, weight) for quick scoring."""
        mapping: dict[str, tuple[str, int]] = {}
        for area in self.expertise:
            for alias in area.aliases:
                mapping[alias.lower()] = (area.name, area.weight)
        for item in self.stack:
            for alias in item.aliases:
                mapping[alias.lower()] = (item.name, item.weight)
        return mapping

    def project_topics(self) -> list[tuple[BWAProject, list[str]]]:
        return [(p, [t.lower() for t in p.topics]) for p in self.projects]


def _load_yaml(name: str) -> dict[str, Any]:
    path = _KNOWLEDGE_DIR / name
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def load_knowledge_base() -> KnowledgeBase:
    """Load all BWA knowledge files into a single object."""
    expertise_data = _load_yaml("expertise.yaml")
    projects_data = _load_yaml("projects.yaml")
    stack_data = _load_yaml("stack.yaml")
    rules_data = _load_yaml("content_rules.yaml")

    expertise = [
        ExpertiseArea(**item)
        for item in expertise_data.get("expertise", [])
    ]
    projects = [
        BWAProject(**item)
        for item in projects_data.get("projects", [])
    ]
    stack = [
        StackItem(**item)
        for item in stack_data.get("stack", [])
    ]
    rules = [
        ContentRule(**item)
        for item in rules_data.get("rules", [])
    ]
    return KnowledgeBase(expertise=expertise, projects=projects, stack=stack, rules=rules)


def match_text_against_knowledge(text: str, kb: KnowledgeBase) -> dict[str, Any]:
    """Score a text snippet against the full knowledge base.

    Returns:
        {
            "expertise_matches": [(name, weight, matched_alias), ...],
            "stack_matches": [(name, weight, matched_alias), ...],
            "project_matches": [(project_name, weight, matched_topics), ...],
            "expertise_score": int,
            "stack_score": int,
            "project_score": int,
            "total_knowledge_score": int,
            "matched_projects": list[str],
        }
    """
    lowered = text.lower()
    aliases = kb.all_aliases()

    expertise_matches: list[tuple[str, int, str]] = []
    stack_matches: list[tuple[str, int, str]] = []
    for alias, (name, weight) in aliases.items():
        if alias in lowered:
            # Decide if alias belongs to expertise or stack.
            area = next((a for a in kb.expertise if a.name == name), None)
            if area:
                expertise_matches.append((name, weight, alias))
            else:
                stack_matches.append((name, weight, alias))

    # Deduplicate by name, keeping highest weight.
    def dedup(matches: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
        best: dict[str, tuple[str, int, str]] = {}
        for name, weight, alias in matches:
            if name not in best or weight > best[name][1]:
                best[name] = (name, weight, alias)
        return list(best.values())

    expertise_matches = dedup(expertise_matches)
    stack_matches = dedup(stack_matches)

    expertise_score = min(sum(w for _, w, _ in expertise_matches), 100)
    stack_score = min(sum(w for _, w, _ in stack_matches), 100)

    # Project matching: does text overlap with project topics?
    project_matches: list[tuple[str, int, list[str]]] = []
    matched_projects: list[str] = []
    for project, topics in kb.project_topics():
        hits = [t for t in topics if t in lowered]
        if hits:
            score = min(len(hits) * project.weight, project.weight)
            project_matches.append((project.name, score, hits))
            matched_projects.append(project.name)

    project_score = min(sum(s for _, s, _ in project_matches), 100)
    total = min(expertise_score + stack_score + project_score, 100)

    return {
        "expertise_matches": expertise_matches,
        "stack_matches": stack_matches,
        "project_matches": project_matches,
        "expertise_score": expertise_score,
        "stack_score": stack_score,
        "project_score": project_score,
        "total_knowledge_score": total,
        "matched_projects": matched_projects,
    }
