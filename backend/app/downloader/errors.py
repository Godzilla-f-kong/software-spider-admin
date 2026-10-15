class DownloadError(Exception):
    def __init__(self, code: str, message: str, retry_after: float | None = None):
        self.code = code
        self.message = message
        self.retry_after = retry_after
        super().__init__(f"{code}: {message}")
