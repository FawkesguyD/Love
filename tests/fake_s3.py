from dataclasses import dataclass


@dataclass
class FakeS3Object:
    data: bytes
    content_type: str | None = None


class FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        return None


class FakeS3Client:
    def __init__(self) -> None:
        self._objects: dict[str, FakeS3Object] = {}

    def put_object(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self._objects[key] = FakeS3Object(data=data, content_type=content_type)

    def list_objects_v2(
        self,
        Bucket: str,
        Prefix: str = "",
        MaxKeys: int = 1000,
        ContinuationToken: str | None = None,
    ) -> dict:
        keys = sorted(key for key in self._objects if key.startswith(Prefix))

        start = 0
        if ContinuationToken is not None:
            try:
                start = int(ContinuationToken)
            except ValueError:
                start = 0

        chunk = keys[start : start + MaxKeys]
        is_truncated = start + MaxKeys < len(keys)

        payload: dict = {
            "IsTruncated": is_truncated,
        }
        if chunk:
            payload["Contents"] = [{"Key": key} for key in chunk]

        if is_truncated:
            payload["NextContinuationToken"] = str(start + MaxKeys)

        return payload

    def get_object(self, Bucket: str, Key: str) -> dict:
        obj = self._objects[Key]
        payload: dict = {"Body": FakeBody(obj.data)}
        if obj.content_type is not None:
            payload["ContentType"] = obj.content_type
        return payload
