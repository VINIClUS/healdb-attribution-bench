"""Shared vocabulary for every workstream.

Owned by the main session: request changes instead of editing (see CLAUDE.md).
"""

from dataclasses import dataclass
from enum import StrEnum

SYSTEM_ICD10CM = "ICD-10-CM"
SYSTEM_ICD10_WHO = "ICD-10-WHO"

# A family of explanations: an antichain of inclusion-minimal factor sets.
Family = frozenset[frozenset[str]]


@dataclass(frozen=True, slots=True, order=True)
class AssocKey:
    """Association key (protocol §5.1).

    version is "acm:<ModelVersion>" for ICD-10-CM codes returned by the ACM and
    "hier:<sha256 prefix of the hierarchy tables>" for WHO ICD-10 codes.
    """

    med: int
    system: str
    version: str
    code: str


class Presence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    # Failed or missing execution: never read as absence of a disease (§5.1).
    UNAVAILABLE = "unavailable"


class ClaimState(StrEnum):
    """State of a reconstructed claim (§6.5)."""

    ARMAZENADO = "armazenado"
    REDERIVADO_VERIFICADO = "rederivado_verificado"
    INFERIDO_COMPATIVEL = "inferido_compativel"
    REFUTADO = "refutado"
    NAO_DETERMINADO = "nao_determinado"


class OutputState(StrEnum):
    """Per-association method output (§7.4)."""

    EXPLICACAO_VERIFICADA = "explicacao_verificada"
    ALTERNATIVAS = "alternativas"
    AUSENCIA_DE_MUDANCA = "ausencia_de_mudanca"
    COMPATIVEL_COM_VARIABILIDADE = "compativel_com_variabilidade"
    INFORMACAO_INSUFICIENTE = "informacao_insuficiente"
    ORCAMENTO_ESGOTADO = "orcamento_esgotado"
    CONTRAFACTUAL_INDISPONIVEL = "contrafactual_indisponivel"
    FALHA_DE_EXECUCAO = "falha_de_execucao"


CATEGORICAL = frozenset({
    OutputState.EXPLICACAO_VERIFICADA,
    OutputState.ALTERNATIVAS,
    OutputState.AUSENCIA_DE_MUDANCA,
    OutputState.COMPATIVEL_COM_VARIABILIDADE,
})

ABSTENTIONS = frozenset({
    OutputState.INFORMACAO_INSUFICIENTE,
    OutputState.ORCAMENTO_ESGOTADO,
    OutputState.CONTRAFACTUAL_INDISPONIVEL,
})


class SealedError(RuntimeError):
    """Raised when code tries to materialize anything from the sealed test partition."""
