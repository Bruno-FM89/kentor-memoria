"""Resolução da identidade de uma chamada MCP.

Um agente mal-comportado pode mandar `identity="socio"` no parâmetro da
ferramenta. Por isso a identidade é FIXADA no processo do servidor
(KENTOR_IDENTITY, definido na configuração do cliente MCP de cada pessoa):

- servidor com identidade fixa + parâmetro diferente → recusado;
- servidor sem identidade fixa → só aceita o parâmetro se
  KENTOR_ALLOW_IDENTITY_PARAM=1 (modo demo/teste, documentado como inseguro);
- caso contrário → recusado (fail closed).
"""
from __future__ import annotations

from ..config import Settings


class IdentityError(PermissionError):
    pass


def resolve_identity(requested: str | None, settings: Settings) -> str:
    requested = (requested or "").strip() or None
    bound = settings.bound_identity
    if bound:
        if requested and requested != bound:
            raise IdentityError(
                f"Este servidor MCP está vinculado à identidade '{bound}'. "
                f"Não é permitido consultar como '{requested}'."
            )
        return bound
    if settings.allow_identity_param and requested:
        return requested
    raise IdentityError(
        "Servidor sem identidade configurada. Defina KENTOR_IDENTITY na configuração do cliente MCP."
    )
