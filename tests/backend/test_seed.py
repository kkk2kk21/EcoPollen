import unittest
from tests.backend import _bootstrap  # noqa: F401

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domain.models import DataSource, PollenTaxon, User
from app.startup.seed import DEFAULT_ADMIN_EMAIL, seed_if_empty
from app.startup.seed import _taxon_model_payload


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_taxon_payload_ignores_catalog_only_fields(self):
        payload = _taxon_model_payload(
            {
                "key": "alder",
                "name_ru": "Ольха",
                "emoji": "🌳",
                "group": "tree",
                "concentration_thresholds": (1, 11, 40, 70, 250),
            }
        )

        self.assertEqual(
            payload,
            {
                "key": "alder",
                "name_ru": "Ольха",
                "emoji": "🌳",
                "group": "tree",
            },
        )

    def test_seed_creates_admin_sources_and_taxa(self):
        seed_if_empty(self.db)

        admin = self.db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        self.assertIsNotNone(admin)
        self.assertEqual(admin.role, "admin")

        sources = self.db.scalars(select(DataSource)).all()
        taxa = self.db.scalars(select(PollenTaxon)).all()

        self.assertGreaterEqual(len(sources), 5)
        self.assertGreaterEqual(len(taxa), 10)

    def test_seed_updates_existing_source_and_taxon(self):
        self.db.add(
            User(
                email="user@example.com",
                password_hash="hash",
                role="student",
            )
        )
        self.db.add(
            DataSource(
                key="pgniu_manual",
                name="Старое имя",
                source_type="legacy",
                priority=1,
                url="https://old.example",
            )
        )
        self.db.add(
            PollenTaxon(
                key="alder",
                name_ru="Старое название",
                emoji="x",
                group="other",
            )
        )
        self.db.commit()

        seed_if_empty(self.db)

        source = self.db.scalar(select(DataSource).where(DataSource.key == "pgniu_manual"))
        taxon = self.db.scalar(select(PollenTaxon).where(PollenTaxon.key == "alder"))

        self.assertEqual(source.name, "Замеры ПГНИУ")
        self.assertEqual(source.source_type, "manual")
        self.assertEqual(source.priority, 100)
        self.assertEqual(taxon.name_ru, "Ольха")
        self.assertEqual(taxon.group, "tree")
