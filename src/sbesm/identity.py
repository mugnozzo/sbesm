import uuid


def generate_storage_id() -> str:
    return str(uuid.uuid4())
