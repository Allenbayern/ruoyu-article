from article_group.delivery import validate_delivery_authorization


def test_not_authorized_rejects_any_authorization_metadata():
    errors = validate_delivery_authorization(
        {
            "publication_authorization": "not_authorized",
            "authorization_by": "controller",
            "authorized_at": "",
            "authorization_ref": "",
            "authorized_publication_scope": "",
        }
    )

    assert errors == ["authorization_metadata_must_be_blank_when_not_authorized"]
