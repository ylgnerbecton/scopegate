from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from scopegate import db
from scopegate.errors import AppError
from scopegate.services import catalog


def publication(expected=0, version=1, status="published", **extra):
    return {
        "expected_version": expected,
        "version": version,
        "status": status,
        "localizations": [
            {"locale": "en", "title": "Market Review", "description": "Original detail", "tags": ["research"]}
        ],
        **extra,
    }


@pytest.mark.integration
def test_publisher_updates_version_and_explicit_null_without_changing_access(seed, actors):
    key = f"test-{uuid4()}"
    created = catalog.publish(actors["catalog"], key, publication(), str(uuid4()))
    body = publication(
        1,
        2,
        avatar_url=None,
        localizations=[
            {"locale": "en", "title": "Updated", "description": None, "tags": []},
            {"locale": "pt", "title": "Revisão", "tags": []},
        ],
    )
    receipt_key = str(uuid4())
    updated = catalog.publish(actors["catalog"], key, body, receipt_key)
    assert updated["id"] == created["id"]
    assert updated["description"] is None
    assert updated["catalog_version"] == 2
    assert catalog.publish(actors["catalog"], key, body, receipt_key) == updated
    with db.transaction() as conn:
        entitlements = db.row(
            conn,
            "SELECT count(*) AS count FROM project_resources WHERE resource_id=:id",
            {"id": created["id"]},
        )
        locales = db.rows(
            conn,
            "SELECT locale FROM resource_localizations WHERE resource_id=:id ORDER BY locale",
            {"id": created["id"]},
        )
    assert entitlements["count"] == 0
    assert [row["locale"] for row in locales] == ["en", "pt"]


@pytest.mark.integration
def test_archive_is_terminal_and_stale_version_conflicts(seed, actors):
    key = f"test-{uuid4()}"
    catalog.publish(actors["catalog"], key, publication(), str(uuid4()))
    catalog.publish(actors["catalog"], key, publication(1, 2, "archived"), str(uuid4()))
    with pytest.raises(AppError) as failure:
        catalog.publish(actors["catalog"], key, publication(2, 3), str(uuid4()))
    assert failure.value.code == "resource_archive_terminal"
    with pytest.raises(AppError) as failure:
        catalog.publish(actors["catalog"], key, publication(1, 2), str(uuid4()))
    assert failure.value.code == "catalog_version_conflict"


@pytest.mark.integration
def test_same_publication_key_rejects_conflicting_payload(seed, actors):
    external, key = f"test-{uuid4()}", str(uuid4())
    catalog.publish(actors["catalog"], external, publication(), key)
    with pytest.raises(AppError) as failure:
        catalog.publish(actors["catalog"], external, publication(1, 2), key)
    assert failure.value.code == "idempotency_conflict"


@pytest.mark.integration
def test_new_key_contention_creates_one_resource_and_one_receipt(seed, actors):
    external, key = f"test-{uuid4()}", str(uuid4())
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=2)
        return catalog.publish(actors["catalog"], external, publication(), key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: publish(), range(2)))
    assert responses[0] == responses[1]
    with db.transaction() as conn:
        count = db.row(conn, "SELECT count(*) AS n FROM resources WHERE external_key=:key", {"key": external})
        receipts = db.row(
            conn, "SELECT count(*) AS n FROM catalog_receipts WHERE external_key=:key", {"key": external}
        )
    assert count["n"] == receipts["n"] == 1


@pytest.mark.integration
def test_omitted_locale_and_metadata_are_preserved(seed, actors):
    key = f"test-{uuid4()}"
    created = catalog.publish(
        actors["catalog"], key, publication(avatar_url="https://assets.example.test/icon.svg"), str(uuid4())
    )
    catalog.publish(
        actors["catalog"],
        key,
        publication(1, 2, localizations=[{"locale": "pt", "title": "Mercado", "tags": []}]),
        str(uuid4()),
    )
    with db.transaction() as conn:
        resource = db.row(conn, "SELECT avatar_url FROM resources WHERE id=:id", {"id": created["id"]})
        english = db.row(
            conn,
            "SELECT description FROM resource_localizations WHERE resource_id=:id AND locale='en'",
            {"id": created["id"]},
        )
    assert resource["avatar_url"] == "https://assets.example.test/icon.svg"
    assert english["description"] == "Original detail"


@pytest.mark.integration
@pytest.mark.parametrize(
    "localized",
    [
        [{"locale": "en", "title": "Overview", "tags": ["same", "same"]}],
        [{"locale": "en", "title": "One", "tags": []}, {"locale": "en", "title": "Two", "tags": []}],
    ],
)
def test_duplicate_localizations_or_tags_fail_before_publication(seed, actors, localized):
    external = f"test-{uuid4()}"
    with pytest.raises(AppError) as failure:
        catalog.publish(actors["catalog"], external, publication(localizations=localized), str(uuid4()))
    assert failure.value.status == 422
    with db.transaction() as conn:
        resource = db.row(conn, "SELECT id FROM resources WHERE external_key=:key", {"key": external})
    assert resource is None
