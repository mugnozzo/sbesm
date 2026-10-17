from sbesm import exitcodes


class SbesmError(Exception):
    exit_code: int


class UsageError(SbesmError):
    exit_code = exitcodes.USAGE_ERROR


class StorageNotFoundError(SbesmError):
    exit_code = exitcodes.STORAGE_NOT_FOUND


class IOFailureError(SbesmError):
    exit_code = exitcodes.IO_FAILURE


class OperationInterruptedError(SbesmError):
    exit_code = exitcodes.INTERRUPTED


class StorageUnavailableError(StorageNotFoundError):
    pass


class StorageIdentityMismatchError(StorageNotFoundError):
    pass


class AmbiguousStorageError(StorageNotFoundError):
    pass
