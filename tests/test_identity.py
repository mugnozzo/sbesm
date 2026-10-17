from sbesm.identity import generate_storage_id


def test_generate_storage_id_is_unique():
    ids = {generate_storage_id() for _ in range(1000)}
    assert len(ids) == 1000
