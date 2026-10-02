"""Controle de acesso: níveis ordenados, regras por caminho e identidades.

O ponto central de segurança é `authorize()`: ele separa candidatos em
permitidos e negados. Só os permitidos viram `Evidence` (que pode sair do
servidor). Dos negados, sai apenas "existe algo" + quem pode responder.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TypeVar

import yaml

T = TypeVar("T")

FRONTMATTER_ACCESS_KEYS = ("acesso", "access", "nivel_acesso", "classificacao", "classification")


class UnknownIdentityError(PermissionError):
    pass


@dataclass(frozen=True)
class Identity:
    name: str
    clearance: str
    rank: int
    description: str = ""
    label: str = ""  # nome de exibição (interface gráfica)


@dataclass(frozen=True)
class Rule:
    pattern: str
    level: str
    owner: str | None = None


class AccessPolicy:
    def __init__(
        self,
        levels: list[str],
        default_level: str,
        rules: list[Rule],
        identities: dict[str, Identity],
        level_labels: dict[str, str] | None = None,
    ):
        if default_level not in levels:
            raise ValueError(f"default_level '{default_level}' não está em levels")
        for r in rules:
            if r.level not in levels:
                raise ValueError(f"Regra '{r.pattern}' usa nível desconhecido '{r.level}'")
        self.levels = levels
        self.default_level = default_level
        self.rules = rules
        self.identities = identities
        self.level_labels = level_labels or {}

    # ------------------------------------------------------------ carga
    @classmethod
    def from_files(cls, policy_file: Path, identities_file: Path) -> "AccessPolicy":
        pol = yaml.safe_load(policy_file.read_text(encoding="utf-8")) or {}
        levels = list(pol.get("levels") or ["team", "restricted"])
        rules = [Rule(r["pattern"], r["level"], r.get("owner")) for r in pol.get("rules") or []]
        ids_raw = (yaml.safe_load(identities_file.read_text(encoding="utf-8")) or {}).get("identities") or {}
        identities: dict[str, Identity] = {}
        for name, spec in ids_raw.items():
            clearance = spec.get("clearance")
            if clearance not in levels:
                raise ValueError(f"Identidade '{name}' tem clearance desconhecido '{clearance}'")
            identities[name] = Identity(
                name, clearance, levels.index(clearance), spec.get("description", ""), spec.get("label") or name.title()
            )
        return cls(levels, pol.get("default_level", levels[0]), rules, identities, pol.get("level_labels") or {})

    # ------------------------------------------------------------ níveis
    def rank(self, level: str) -> int:
        # nível desconhecido é tratado como o MAIS restrito (fail closed)
        return self.levels.index(level) if level in self.levels else len(self.levels)

    def _rule_for(self, rel_path: str) -> Rule | None:
        for r in self.rules:
            if fnmatch.fnmatchcase(rel_path, r.pattern):
                return r
        return None

    def classify(self, rel_path: str, frontmatter: dict[str, Any] | None = None) -> str:
        """Nível de um documento. Frontmatter só pode SUBIR o nível da regra."""
        rule = self._rule_for(rel_path)
        level = rule.level if rule else self.default_level
        for key in FRONTMATTER_ACCESS_KEYS:
            declared = str((frontmatter or {}).get(key, "")).strip().lower()
            if declared in self.levels and self.rank(declared) > self.rank(level):
                level = declared
        return level

    def owner_hint(self, rel_path: str) -> str | None:
        rule = self._rule_for(rel_path)
        return rule.owner if rule else None

    # ------------------------------------------------------------ identidades
    def identity(self, name: str | None) -> Identity:
        if not name or name not in self.identities:
            raise UnknownIdentityError(f"Identidade desconhecida: {name!r}")
        return self.identities[name]

    def can_read(self, identity: Identity, level: str) -> bool:
        return self.rank(level) <= identity.rank

    def authorize(self, identity: Identity, items: Iterable[T], level_of) -> tuple[list[T], list[T]]:
        """Separa itens em (permitidos, negados). ÚNICO ponto de decisão de acesso."""
        allowed: list[T] = []
        denied: list[T] = []
        for it in items:
            (allowed if self.can_read(identity, level_of(it)) else denied).append(it)
        return allowed, denied
