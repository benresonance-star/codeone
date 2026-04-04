from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from app.services.ingestion import IngestionService
from app.services.retention import RetentionService
from app.services.xml_schema_registry import SCHEMA_NORMALIZER_VERSION, XmlSchemaRegistryService


def _bind_storage(service: XmlSchemaRegistryService, storage_root: Path) -> XmlSchemaRegistryService:
    service._storage_root = storage_root
    service._registry_root = storage_root / "schema-registry"
    service._registry_root.mkdir(parents=True, exist_ok=True)
    service._batch_root = service._registry_root / "batches"
    service._batch_root.mkdir(parents=True, exist_ok=True)
    service._approved_registry_path = service._registry_root / "approved_schema_registry.json"
    service._approved_tag_registry_path = service._registry_root / "approved_tag_schema_registry.json"
    service._observed_registry_path = service._registry_root / "observed_schema_registry.json"
    service._repo_registry_root = storage_root.parent / "data" / "schema-registry"
    service._repo_registry_root.mkdir(parents=True, exist_ok=True)
    service._repo_approved_registry_path = service._repo_registry_root / "approved_schema_registry.json"
    service._repo_approved_tag_registry_path = service._repo_registry_root / "approved_tag_schema_registry.json"
    return service


class XmlSchemaRegistryServiceTests(unittest.TestCase):
    def test_fingerprint_generation_is_stable_for_repeated_shape(self) -> None:
        service = XmlSchemaRegistryService()
        first = ET.fromstring(b"<clause id='c1'><title>A</title><p>Body</p></clause>")
        second = ET.fromstring(b"<clause id='c9'><title>B</title><p>Different body</p></clause>")

        first_fp = service.build_structural_fingerprint(first, source_path="Spec/a.xml")
        second_fp = service.build_structural_fingerprint(second, source_path="Spec/b.xml")

        self.assertEqual(first_fp["fingerprint_hash"], second_fp["fingerprint_hash"])
        self.assertEqual(first_fp["path_signature"], "clause>p|title")
        self.assertEqual(first_fp["child_tag_signature"], "p, title")

    def test_tree_summary_captures_nested_elements_and_paths(self) -> None:
        service = XmlSchemaRegistryService()
        root = ET.fromstring(
            b"<page id='p1' outputclass='page'><title>Main</title><p>Lead <xref href='#t1'>See table</xref></p><section id='s1'><title>Nested</title><table id='t1'><row><entry>Value</entry></row></table></section></page>"
        )

        summary = service._summarize_xml_tree(root)

        self.assertIn("xref", summary["all_element_tags"])
        self.assertIn("title", summary["all_element_tags"])
        self.assertEqual(summary["element_tag_counts"]["title"], 2)
        self.assertEqual(summary["attribute_name_counts"]["id"], 3)
        self.assertEqual(summary["max_depth"], 4)
        self.assertIn("page/p/xref", summary["_tree_path_counts"])
        self.assertIn("page/p/xref", summary["highlighted_paths"]["xref"])

    def test_tag_fingerprint_generation_is_stable_across_reusable_contexts(self) -> None:
        service = XmlSchemaRegistryService()
        root = ET.fromstring(
            b"<page id='page_1'><title>Page title</title><section id='sec_1'><title>Section title</title><table-reference id='tbl_1'><title>Table title</title></table-reference></section></page>"
        )

        observations = service._summarize_tag_schemas(
            root,
            source_path="Spec/reusable-title.xml",
            approved_registry=service.load_approved_tag_registry(),
        )
        title_hashes = {
            observation["tag_fingerprint_hash"] for observation in observations if observation["tag_name"] == "title"
        }
        title_paths = {observation["context_path"] for observation in observations if observation["tag_name"] == "title"}

        self.assertEqual(len(title_hashes), 1)
        self.assertEqual(
            title_paths,
            {
                "page/title",
                "page/section/title",
                "page/section/table-reference/title",
            },
        )

    def test_scan_clusters_repeated_shapes_into_observed_families(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            spec_root = temp_root / "Spec" / "Corpus"
            spec_root.mkdir(parents=True, exist_ok=True)
            (spec_root / "a.xml").write_text("<clause id='a'><title>A</title><p>One</p></clause>", encoding="utf-8")
            (spec_root / "b.xml").write_text("<clause id='b'><title>B</title><p>Two</p></clause>", encoding="utf-8")
            (spec_root / "gloss.xml").write_text(
                "<abcb-glossentry id='g' outputclass='abcb-glossentry'><glossterm>Accessible</glossterm><glossdef><p>Meaning</p></glossdef></abcb-glossentry>",
                encoding="utf-8",
            )
            with patch("app.services.xml_schema_registry.project_root", return_value=temp_root):
                service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
                registry = service.scan_repo_xml_corpus()

        self.assertEqual(registry["scanned_file_count"], 3)
        self.assertEqual(registry["family_count"], 2)
        clause_family = next(item for item in registry["families"] if item["root_tag"] == "clause")
        self.assertEqual(clause_family["file_count"], 2)
        self.assertEqual(clause_family["status"], "variant")

    def test_scan_merges_full_tree_summary_for_same_fingerprint_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            spec_root = temp_root / "Spec" / "Corpus"
            spec_root.mkdir(parents=True, exist_ok=True)
            (spec_root / "a.xml").write_text(
                "<clause id='a'><title>A</title><p>One <xref href='#t1'>Link</xref></p></clause>",
                encoding="utf-8",
            )
            (spec_root / "b.xml").write_text(
                "<clause id='b'><title>B</title><p>Two <note>Nested note</note></p></clause>",
                encoding="utf-8",
            )
            with patch("app.services.xml_schema_registry.project_root", return_value=temp_root):
                service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
                registry = service.scan_repo_xml_corpus()

        clause_family = next(item for item in registry["families"] if item["root_tag"] == "clause")
        self.assertEqual(clause_family["fingerprint_hash"], service.build_structural_fingerprint(ET.fromstring(b"<clause id='c'><title>C</title><p>Three</p></clause>"))["fingerprint_hash"])
        self.assertIn("xref", clause_family["all_element_tags"])
        self.assertIn("note", clause_family["all_element_tags"])
        self.assertEqual(clause_family["element_tag_counts"]["title"], 2)
        self.assertEqual(clause_family["tree_node_count"], 8)
        self.assertTrue(any(item["path"] == "clause/p/xref" for item in clause_family["common_paths"]))

    def test_scan_collects_global_tag_schemas_and_context_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            spec_root = temp_root / "Spec" / "Corpus"
            spec_root.mkdir(parents=True, exist_ok=True)
            (spec_root / "a.xml").write_text(
                "<page id='page_1'><title>Page title</title><section id='sec_1'><title>Section title</title><p>Lead <xref href='#x1'>See</xref></p><table-reference id='tbl_1'><title>Table title</title></table-reference></section></page>",
                encoding="utf-8",
            )
            with patch("app.services.xml_schema_registry.project_root", return_value=temp_root):
                service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
                registry = service.scan_repo_xml_corpus()

        self.assertGreaterEqual(registry["tag_count"], 2)
        title_tag = next(item for item in registry["tags"] if item["tag_name"] == "title")
        self.assertEqual(title_tag["occurrence_count"], 3)
        self.assertTrue(any(item["tag"] == "page" for item in title_tag["common_parent_tags"]))
        self.assertTrue(any(item["tag"] == "section" for item in title_tag["common_parent_tags"]))
        self.assertTrue(any(item["tag"] == "table-reference" for item in title_tag["common_parent_tags"]))
        self.assertTrue(any(item["path"] == "page/section/table-reference/title" for item in title_tag["common_paths"]))

        xref_tag = next(item for item in registry["tags"] if item["tag_name"] == "xref")
        self.assertEqual(xref_tag["occurrence_count"], 1)
        self.assertTrue(any(item["tag"] == "p" for item in xref_tag["common_parent_tags"]))

    def test_approve_observed_family_promotes_registry_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            spec_root = temp_root / "Spec"
            spec_root.mkdir(parents=True, exist_ok=True)
            (spec_root / "custom.xml").write_text("<custom-root><item /></custom-root>", encoding="utf-8")
            with patch("app.services.xml_schema_registry.project_root", return_value=temp_root):
                service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
                observed = service.scan_repo_xml_corpus()
                fingerprint_hash = observed["families"][0]["fingerprint_hash"]
                approval = service.approve_observed_family(fingerprint_hash=fingerprint_hash)
                approved_registry = service.load_approved_registry()

        self.assertEqual(approval["fingerprint_hash"], fingerprint_hash)
        approved_family = next(
            item for item in approved_registry["families"] if fingerprint_hash in item.get("approved_fingerprint_hashes", [])
        )
        self.assertTrue(str(approved_family["schema_family_id"]).endswith("_family"))
        self.assertEqual(approved_family["schema_family_NCC_version"], "2022")
        self.assertTrue(str(approved_registry["registry_version"]).startswith("approved_"))

    def test_runtime_seed_exports_repo_registry_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            with patch("app.services.xml_schema_registry.project_root", return_value=temp_root):
                service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
                registry = service.load_approved_registry()
                repo_sync = registry["repo_sync"]
                self.assertEqual(repo_sync["repo_path"], "data/schema-registry/approved_schema_registry.json")
                self.assertEqual(repo_sync["export_status"], "synced")
                self.assertEqual(registry["families"][0]["schema_family_NCC_version"], "2022")
                self.assertTrue((temp_root / "data" / "schema-registry" / "approved_schema_registry.json").exists())

    def test_runtime_seed_exports_repo_tag_registry_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            with patch("app.services.xml_schema_registry.project_root", return_value=temp_root):
                service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
                registry = service.load_approved_tag_registry()
                repo_sync = registry["repo_sync"]
                self.assertEqual(repo_sync["repo_path"], "data/schema-registry/approved_tag_schema_registry.json")
                self.assertEqual(repo_sync["export_status"], "synced")
                self.assertTrue((temp_root / "data" / "schema-registry" / "approved_tag_schema_registry.json").exists())

    def test_uploaded_batch_scan_clusters_repeated_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")

            batch = service.scan_uploaded_xml_batch(
                [
                    ("a.xml", b"<clause id='a'><title>A</title><p>One</p></clause>"),
                    ("b.xml", b"<clause id='b'><title>B</title><p>Two</p></clause>"),
                    (
                        "gloss.xml",
                        b"<abcb-glossentry outputclass='abcb-glossentry'><glossterm>Accessible</glossterm><glossdef><p>Meaning</p></glossdef></abcb-glossentry>",
                    ),
                ]
            )

        self.assertTrue(batch["batch_job_id"].startswith("batch_"))
        self.assertEqual(batch["uploaded_file_count"], 3)
        self.assertEqual(batch["scanned_file_count"], 3)
        self.assertEqual(batch["family_count"], 2)
        clause_family = next(item for item in batch["families"] if item["root_tag"] == "clause")
        self.assertEqual(clause_family["file_count"], 2)
        self.assertIn("a.xml", clause_family["files"])

    def test_uploaded_batch_scan_merges_tags_into_observed_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")

            batch = service.scan_uploaded_xml_batch(
                [
                    (
                        "footnote.xml",
                        b"<page id='page_1'><title>Footnote</title><p>Lead <xref href='#a1'>xref</xref></p><section id='sec_1'><title>Section title</title></section></page>",
                    )
                ]
            )
            observed = service.load_observed_registry()

        self.assertTrue(batch["observed_merge_applied"])
        self.assertEqual(batch["observed_registry_version"], observed["registry_version"])
        self.assertEqual(observed["scanned_file_count"], 1)
        self.assertEqual(observed["family_count"], 1)
        self.assertGreaterEqual(observed["tag_count"], 4)
        title_tag = next(item for item in observed["tags"] if item["tag_name"] == "title")
        self.assertEqual(title_tag["occurrence_count"], 2)
        self.assertTrue(any(item["path"] == "page/title" for item in title_tag["common_paths"]))
        self.assertTrue(any(item["path"] == "page/section/title" for item in title_tag["common_paths"]))
        xref_tag = next(item for item in observed["tags"] if item["tag_name"] == "xref")
        self.assertTrue(any(item["path"] == "page/p/xref" for item in xref_tag["common_paths"]))

    def test_repeated_uploaded_batch_merge_does_not_duplicate_observed_tag_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
            xml_payload = b"<page id='page_1'><title>Footnote</title><section id='sec_1'><title>Section title</title></section></page>"

            service.scan_uploaded_xml_batch([("footnote.xml", xml_payload)])
            first_observed = service.load_observed_registry()
            service.scan_uploaded_xml_batch([("footnote.xml", xml_payload)])
            second_observed = service.load_observed_registry()

        first_title_tag = next(item for item in first_observed["tags"] if item["tag_name"] == "title")
        second_title_tag = next(item for item in second_observed["tags"] if item["tag_name"] == "title")
        self.assertEqual(first_title_tag["occurrence_count"], second_title_tag["occurrence_count"])
        self.assertEqual(first_title_tag["file_count"], second_title_tag["file_count"])
        self.assertEqual(second_observed["family_count"], 1)
        self.assertEqual(second_observed["tag_count"], first_observed["tag_count"])

    def test_uploaded_batch_scan_reports_invalid_and_non_xml_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")

            batch = service.scan_uploaded_xml_batch(
                [
                    ("valid.xml", b"<clause id='a'><title>A</title><p>One</p></clause>"),
                    ("broken.xml", b"<clause><title>Broken</title>"),
                    ("notes.txt", b"not xml"),
                ]
            )

        self.assertEqual(batch["uploaded_file_count"], 3)
        self.assertEqual(batch["scanned_file_count"], 1)
        self.assertEqual(len(batch["scan_errors"]), 2)
        self.assertTrue(any(item["file"] == "broken.xml" for item in batch["scan_errors"]))
        self.assertTrue(any(item["file"] == "notes.txt" for item in batch["scan_errors"]))

    def test_approve_observed_family_promotes_uploaded_batch_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
            batch = service.scan_uploaded_xml_batch([("custom.xml", b"<custom-root><item /></custom-root>")])
            fingerprint_hash = batch["families"][0]["fingerprint_hash"]

            approval = service.approve_observed_family(
                fingerprint_hash=fingerprint_hash,
                registry_type="batch",
                batch_job_id=batch["batch_job_id"],
            )
            approved_registry = service.load_approved_registry()

        self.assertEqual(approval["fingerprint_hash"], fingerprint_hash)
        approved_family = next(
            item for item in approved_registry["families"] if fingerprint_hash in item.get("approved_fingerprint_hashes", [])
        )
        self.assertTrue(str(approved_family["schema_family_id"]).endswith("_family"))

    def test_approve_observed_tag_promotes_registry_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            spec_root = temp_root / "Spec"
            spec_root.mkdir(parents=True, exist_ok=True)
            (spec_root / "custom.xml").write_text(
                "<page id='page_1'><section id='sec_1'><title>Section title</title></section></page>",
                encoding="utf-8",
            )
            with patch("app.services.xml_schema_registry.project_root", return_value=temp_root):
                service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
                observed = service.scan_repo_xml_corpus()
                tag_fingerprint_hash = next(
                    item["tag_fingerprint_hash"] for item in observed["tags"] if item["tag_name"] == "title"
                )
                approval = service.approve_observed_tag(tag_fingerprint_hash=tag_fingerprint_hash)
                approved_registry = service.load_approved_tag_registry()

        self.assertEqual(approval["tag_fingerprint_hash"], tag_fingerprint_hash)
        approved_tag = next(
            item for item in approved_registry["tags"] if tag_fingerprint_hash in item.get("approved_tag_fingerprint_hashes", [])
        )
        self.assertEqual(approved_tag["schema_tag_id"], "title")
        self.assertTrue(any(item["path"] == "page/section/title" for item in approved_tag["common_paths"]))

    def test_repo_sync_detects_drift_when_checked_in_artifact_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
            registry = service.load_approved_registry()
            repo_path = temp_root / "data" / "schema-registry" / "approved_schema_registry.json"
            repo_payload = json.loads(repo_path.read_text(encoding="utf-8"))
            repo_payload["families"] = []
            repo_path.write_text(json.dumps(repo_payload, indent=2), encoding="utf-8")

            reloaded = service.load_approved_registry()

        self.assertEqual(registry["repo_sync"]["export_status"], "synced")
        self.assertTrue(reloaded["repo_sync"]["drift_detected"])
        self.assertEqual(reloaded["repo_sync"]["export_status"], "drifted")

    def test_runtime_match_uses_approved_registry_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")
            root = ET.fromstring(b"<abcb-glossentry outputclass='abcb-glossentry'><glossterm>Accessible</glossterm><glossdef><p>Meaning</p></glossdef></abcb-glossentry>")

            match = service.match_against_approved_registry(root)

        self.assertEqual(match["schema_family_id"], "abcb_glossentry")
        self.assertEqual(match["schema_family_version"], "1")
        self.assertEqual(match["normalizer_version"], SCHEMA_NORMALIZER_VERSION)
        self.assertEqual(match["registry_version"], "approved_seed_v1")


class IngestionSchemaRegistryIntegrationTests(unittest.TestCase):
    def test_validate_xml_surfaces_registry_context_on_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            service = IngestionService()
            service.schema_registry = _bind_storage(XmlSchemaRegistryService(), temp_root / "runtime-data")

            result = service._validate_xml(
                b"<abcb-glossentry id='entry_1' outputclass='abcb-glossentry' edition='2022' volume='1' amendment='base' part='Schedule 1'><glossterm id='term_1'>Accessible</glossterm><glossdef><p>Meaning</p></glossdef></abcb-glossentry>",
                "glossary-accessible.xml",
            )

        self.assertEqual(result["metrics"]["schema_family_id"], "abcb_glossentry")
        self.assertEqual(result["metrics"]["schema_family_version"], "1")
        self.assertEqual(result["metrics"]["schema_registry_version"], "approved_seed_v1")
        self.assertEqual(result["result"]["document"]["schema_family_version"], "1")
        self.assertEqual(result["result"]["document"]["schema_registry_version"], "approved_seed_v1")
        self.assertEqual(result["result"]["document"]["schema_normalizer_version"], SCHEMA_NORMALIZER_VERSION)

    def test_validate_xml_builds_context_descriptors_for_nested_nodes(self) -> None:
        service = IngestionService()
        result = service._validate_xml(
            b"<page id='page_1' outputclass='page'><title>Footnote</title><section id='sec_1'><title>Section A</title><p id='p_1'>Lead paragraph text with nested <xref href='#ref_1'>xref</xref> context for lineage checks.</p><table-reference id='tbl_1'><title>Table Title</title><table id='ref_1'><tbody><row><entry>Value</entry></row></tbody></table></table-reference></section></page>",
            "nested-footnote.xml",
        )

        xml_nodes = result["xml_nodes"]
        paragraph_node = next(node for node in xml_nodes if node.node_id == "p_1")
        self.assertIsNotNone(paragraph_node.context_descriptor)
        self.assertEqual(
            paragraph_node.context_descriptor.full_path,
            "/page[@id='page_1']/section[@id='sec_1']/p[@id='p_1']",
        )
        self.assertEqual(paragraph_node.context_descriptor.root_node_id, "page_1")
        self.assertEqual(paragraph_node.context_descriptor.parent_node_id, "sec_1")
        self.assertEqual(paragraph_node.context_descriptor.ancestor_node_ids, ["page_1", "sec_1"])
        self.assertIn("Footnote", paragraph_node.context_descriptor.context_titles)
        self.assertIn("Section A", paragraph_node.context_descriptor.context_titles)

        table_row_node = next(node for node in xml_nodes if node.node_id == "tbl_1__row_1")
        self.assertIsNotNone(table_row_node.context_descriptor)
        self.assertEqual(table_row_node.context_descriptor.parent_node_id, "tbl_1")
        self.assertTrue(table_row_node.context_descriptor.full_path.endswith("/tbody/row[1]"))

    def test_candidate_objects_include_xml_context_descriptor_fields(self) -> None:
        service = IngestionService()
        result = service._validate_xml(
            b"<page id='page_1' outputclass='page'><section id='sec_1'><title>Section A</title><p id='p_1'>Lead text for review candidate.</p></section></page>",
            "candidate-context.xml",
        )

        candidates = service._build_candidate_objects(
            semantic_units=result["semantic_units"],
            pdf_evidence_packets=[],
        )

        candidate = next(item for item in candidates if item["xml_node_id"] == "p_1")
        self.assertEqual(
            candidate["xml_full_path"],
            "/page[@id='page_1']/section[@id='sec_1']/p[@id='p_1']",
        )
        self.assertEqual(candidate["xml_parent_node_id"], "sec_1")
        self.assertEqual(candidate["xml_root_node_id"], "page_1")
        self.assertEqual(candidate["xml_ancestor_node_ids"], ["page_1", "sec_1"])
        self.assertEqual(candidate["xml_ancestor_tags"], ["page", "section"])
        self.assertEqual(candidate["xml_context_path_signature"], "page/section/p")
        self.assertEqual(candidate["xml_context_descriptor"]["node_id"], "p_1")

    def test_retention_serializer_preserves_xml_context_descriptor(self) -> None:
        service = IngestionService()
        retention = RetentionService()
        result = service._validate_xml(
            b"<page id='page_1' outputclass='page'><section id='sec_1'><title>Section A</title><p id='p_1'>Lead text for retention serializer.</p></section></page>",
            "retention-context.xml",
        )

        paragraph_node = next(node for node in result["xml_nodes"] if node.node_id == "p_1")
        payload = retention._serialize_xml_node(paragraph_node)

        self.assertEqual(payload["full_path"], "/page[@id='page_1']/section[@id='sec_1']/p[@id='p_1']")
        self.assertEqual(payload["parent_node_id"], "sec_1")
        self.assertEqual(payload["root_node_id"], "page_1")
        self.assertEqual(payload["ancestor_node_ids"], ["page_1", "sec_1"])
        self.assertEqual(payload["context_path_signature"], "page/section/p")
        self.assertEqual(payload["context_descriptor"]["nearest_structural_parent_id"], "sec_1")


class SchemaReviewFrontendContractTests(unittest.TestCase):
    def test_schema_review_panel_is_mounted_on_dedicated_page(self) -> None:
        workspace_root = Path(__file__).resolve().parents[2]
        schema_page = (workspace_root / "frontend" / "app" / "schema-review" / "page.tsx").read_text(encoding="utf-8")
        home_page = (workspace_root / "frontend" / "app" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("SchemaReviewPanel", schema_page)
        self.assertNotIn("<SchemaReviewPanel", home_page)

    def test_console_navigation_exposes_schema_review_tab(self) -> None:
        workspace_root = Path(__file__).resolve().parents[2]
        navigation = (workspace_root / "frontend" / "components" / "console-navigation.tsx").read_text(encoding="utf-8")

        self.assertIn('href: "/schema-review"', navigation)
        self.assertIn('label: "Schema review"', navigation)

    def test_schema_review_panel_supports_family_tag_and_raw_views(self) -> None:
        workspace_root = Path(__file__).resolve().parents[2]
        component = (workspace_root / "frontend" / "components" / "schema-review-panel.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn("Root family registry", component)
        self.assertIn("Global tag registry", component)
        self.assertIn("Human-readable view", component)
        self.assertIn("Raw JSON view", component)
        self.assertIn("Approved registry JSON", component)
        self.assertIn("mermaid.render", component)

    def test_schema_review_panel_renders_architecture_explainer(self) -> None:
        workspace_root = Path(__file__).resolve().parents[2]
        component = (workspace_root / "frontend" / "components" / "schema-review-panel.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn("How discovery becomes runtime lineage", component)
        self.assertIn("Reusable tag extraction", component)
        self.assertIn("Ingestion lineage", component)
        self.assertIn("schema-architecture-visual", component)

    def test_frontend_package_includes_mermaid_dependency(self) -> None:
        workspace_root = Path(__file__).resolve().parents[2]
        package_json = (workspace_root / "frontend" / "package.json").read_text(encoding="utf-8")

        self.assertIn('"mermaid"', package_json)
