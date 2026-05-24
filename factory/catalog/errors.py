# errors.py — Module-specific errors for catalog
#
# Defines the exception hierarchy for catalog. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class CatalogError(FactoryError):
    """Base exception for the catalog module."""

    pass


class ManifestValidationError(CatalogError):
    """Raised when manifest validation fails."""

    pass


class CatalogLicenseViolation(CatalogError):
    """Raised when simulator dependency graph contains license violations."""

    pass


class ContainerBuildFailed(CatalogError):
    """Raised when container image build fails."""

    pass


class SmokeTestFailed(CatalogError):
    """Raised when the container smoke test fails or residuals exceed tolerance."""

    pass


class EntryQuarantined(CatalogError):
    """Raised when trying to retrieve/use a quarantined simulator entry."""

    pass


class ManifestRegistryDrift(CatalogError):
    """Raised when the registry database index drifts from manifest files on disk."""

    pass


class CatalogLookupError(CatalogError):
    """Raised when looking up a non-existent simulator entry in the catalog."""

    pass
