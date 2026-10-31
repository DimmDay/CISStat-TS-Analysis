"""Safe domain errors: never include driver messages, DSNs or secret values."""


class AuthStoreUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("auth_store_unavailable")


class AuthSchemaNotReady(RuntimeError):
    def __init__(self):
        super().__init__("auth_schema_not_ready")


class RepositoryConflict(RuntimeError):
    def __init__(self):
        super().__init__("auth_storage_constraint_violation")


class VersionConflict(RuntimeError):
    def __init__(self):
        super().__init__("auth_version_conflict")


class RecordNotFound(RuntimeError):
    def __init__(self):
        super().__init__("auth_record_not_found")
