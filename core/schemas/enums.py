"""
core/schemas/enums.py
All categorical enums used across the DYNAFIT pipeline.
Never create new enums elsewhere — always import from here.
"""
from enum import Enum


class D365Module(str, Enum):
    """Microsoft Dynamics 365 F&O module codes."""

    AP = "AP"                          # Accounts Payable
    AR = "AR"                          # Accounts Receivable
    GL = "GL"                          # General Ledger
    FA = "FA"                          # Fixed Assets
    SCM = "SCM"                        # Supply Chain Management
    WMS = "WMS"                        # Warehouse Management
    MFG = "MFG"                        # Manufacturing
    PM = "PM"                          # Project Management
    HR = "HR"                          # Human Resources
    PAYROLL = "PAYROLL"                # Payroll
    BUDGET = "BUDGET"                  # Budgeting
    CASH = "CASH"                      # Cash & Bank Management
    TAX = "TAX"                        # Tax
    CONSOLIDATION = "CONSOLIDATION"   # Financial Consolidation
    UNKNOWN = "UNKNOWN"                # Could not determine module


class MoSCoW(str, Enum):
    """MoSCoW priority classification for requirements."""

    MUST = "MUST"        # Mandatory — system won't be accepted without this
    SHOULD = "SHOULD"    # Expected — high-value but not critical
    COULD = "COULD"      # Nice to have — included if resources allow
    WONT = "WONT"        # Explicitly out of scope for this delivery


class IntentType(str, Enum):
    """Classification of the requirement's intent."""

    FUNCTIONAL = "FUNCTIONAL"              # Standard business function
    NFR = "NFR"                            # Non-functional (performance, security)
    INTEGRATION = "INTEGRATION"            # System integration requirement
    REPORTING = "REPORTING"                # Reporting / analytics requirement
    DATA_MIGRATION = "DATA_MIGRATION"      # Data migration requirement


class Verdict(str, Enum):
    """Fitment verdict — the core output of the classification phase."""

    FIT = "FIT"                  # D365 covers requirement fully out-of-the-box
    PARTIAL_FIT = "PARTIAL_FIT"  # D365 partially covers; config or ISV needed
    GAP = "GAP"                  # D365 does not cover; custom development required


class RouteDecision(str, Enum):
    """Phase 3 → Phase 4 routing decision."""

    FAST_TRACK = "FAST_TRACK"  # High confidence + historical precedent → auto-FIT
    LLM = "LLM"                # Standard path — LLM chain-of-thought reasoning
    SOFT_GAP = "SOFT_GAP"      # Low confidence + no candidates → auto-GAP


class ConfidenceBand(str, Enum):
    """Semantic confidence band derived from composite score."""

    HIGH = "HIGH"    # composite >= 0.70
    MED = "MED"      # composite 0.40-0.69
    LOW = "LOW"      # composite < 0.40


class AtomStatus(str, Enum):
    """Processing status of a RequirementAtom."""

    ACTIVE = "ACTIVE"              # Normal processing
    ERROR = "ERROR"                # Failed during processing
    DUPLICATE = "DUPLICATE"        # Deduplicated — not processed
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # Explicitly excluded


class RunStatus(str, Enum):
    """Overall pipeline run status."""

    QUEUED = "QUEUED"                    # Run created, not yet started
    RUNNING = "RUNNING"                  # Pipeline executing
    AWAITING_REVIEW = "AWAITING_REVIEW"  # Interrupted for human review
    COMPLETED = "COMPLETED"              # Successfully finished
    FAILED = "FAILED"                    # Unrecoverable failure
    CANCELLED = "CANCELLED"              # Manually cancelled
