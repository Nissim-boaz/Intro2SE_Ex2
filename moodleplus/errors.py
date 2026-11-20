"""שגיאות של שכבת ה-Service. ההודעה תמיד מוכנה להצגה למשתמש."""


class ServiceError(Exception):
    status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(ServiceError):
    status = 400


class NotFound(ServiceError):
    status = 404


class Forbidden(ServiceError):
    status = 403
