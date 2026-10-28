from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_revision_identifiers_fit_the_default_alembic_version_column():
    script = ScriptDirectory.from_config(Config("backend/alembic.ini"))
    revision_identifiers = [
        revision.revision
        for revision in script.walk_revisions(base="base", head="heads")
    ]

    assert len(revision_identifiers) == len(set(revision_identifiers))
    assert all(len(revision_identifier) <= 32 for revision_identifier in revision_identifiers)
