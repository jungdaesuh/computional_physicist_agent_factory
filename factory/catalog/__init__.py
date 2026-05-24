# __init__.py — Public exports for the catalog module
#
# This file exports the public API of the catalog module. Other modules should
# only import from `factory.catalog`, not from internal files.

import logging

from factory.catalog.api import (
    CarveOutLicense,
    Catalog,
    CatalogEntry,
    ContainerRecipe,
    DependencyGraph,
    DependencyNode,
    EntryStatus,
    EquivalencePair,
    IOSchema,
    KnownPathology,
    LicenseAuditReport,
    LicenseFinding,
    MaintenanceSignal,
    OsiApprovedLicense,
    ReverificationReport,
    SimulatorCapabilities,
    SimulatorManifest,
    SmokeTestRecord,
    compute_manifest_hash,
)
from factory.catalog.build import (
    ApptainerContainerRuntime,
    BuildCommand,
    BuildCommandRunner,
    BuildManager,
    BuildRequest,
    BuildResult,
    ContainerRuntime,
    DockerContainerRuntime,
    MockContainerRuntime,
    VerifiedBuildRecipe,
    verify_build_recipe,
)
from factory.catalog.errors import (
    CatalogError,
    CatalogLicenseViolation,
    CatalogLookupError,
    ContainerBuildFailed,
    EntryQuarantined,
    ManifestRegistryDrift,
    ManifestValidationError,
    SmokeTestFailed,
)
from factory.catalog.gate import (
    HumanGateRecord,
    approve_onboarding,
    reject_onboarding,
)
from factory.catalog.license import (
    LicensePolicy,
    audit_manifest_dependencies,
    audit_manifest_path,
)
from factory.catalog.onboard import (
    DependencyProposal,
    ManifestProposal,
    propose_manifest_from_repo,
)
from factory.catalog.smoke import (
    SmokeBaseline,
    SmokeComparison,
    StaticSmokeRuntime,
    compare_smoke_outputs,
    run_smoke_against_baseline,
)

logger = logging.getLogger("factory.catalog")

# Public exports
__all__ = [
    "CatalogError",
    "ManifestValidationError",
    "CatalogLicenseViolation",
    "ContainerBuildFailed",
    "SmokeTestFailed",
    "EntryQuarantined",
    "ManifestRegistryDrift",
    "CatalogLookupError",
    "OsiApprovedLicense",
    "CarveOutLicense",
    "IOSchema",
    "ContainerRecipe",
    "DependencyNode",
    "DependencyGraph",
    "MaintenanceSignal",
    "KnownPathology",
    "EquivalencePair",
    "SimulatorCapabilities",
    "SimulatorManifest",
    "EntryStatus",
    "SmokeTestRecord",
    "CatalogEntry",
    "LicenseFinding",
    "LicenseAuditReport",
    "ReverificationReport",
    "Catalog",
    "compute_manifest_hash",
    "BuildManager",
    "BuildCommand",
    "BuildCommandRunner",
    "BuildRequest",
    "BuildResult",
    "ContainerRuntime",
    "DockerContainerRuntime",
    "ApptainerContainerRuntime",
    "MockContainerRuntime",
    "VerifiedBuildRecipe",
    "verify_build_recipe",
    "LicensePolicy",
    "audit_manifest_dependencies",
    "audit_manifest_path",
    "DependencyProposal",
    "ManifestProposal",
    "propose_manifest_from_repo",
    "SmokeBaseline",
    "SmokeComparison",
    "StaticSmokeRuntime",
    "compare_smoke_outputs",
    "run_smoke_against_baseline",
    "HumanGateRecord",
    "approve_onboarding",
    "reject_onboarding",
]
