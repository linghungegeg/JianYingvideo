class JianYingServiceError(Exception):
    pass


class ValidationError(JianYingServiceError):
    pass


class NotFoundError(JianYingServiceError):
    pass
