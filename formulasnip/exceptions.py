class FormulaSnipError(RuntimeError):
    """Base exception shown as a friendly application error."""


class BackendUnavailableError(FormulaSnipError):
    """Raised when the selected local recognition backend is unavailable."""


class RecognitionError(FormulaSnipError):
    """Raised when a backend cannot recognize the supplied image."""


class WordIntegrationError(FormulaSnipError):
    """Raised when a formula cannot be inserted into Microsoft Word."""
