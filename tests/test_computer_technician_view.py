"""
The computer detail a technician can actually work from.

The enriched view used to print GLPI's internal device ids -- "CPU ID 109",
"Mem ID 98" -- and an empty software column. Every fact a support call needs
(processor model, memory type and form factor, free disk space, whether the
antivirus is current) was either fetched and discarded or one `expand_dropdowns`
away. These tests pin the reading, not the fetching.
"""

from src.formatters.glpi_formatters import (
    _blank_to_dash,
    _fmt_mb,
    _is_blank,
    format_computer_details_enriched,
)
from src.tools.assets import _subitem_link_id


def _render(**sections):
    payload = {"asset": {"id": 3, "name": "WS019", "asset_type": "Computer"}}
    payload.update(sections)
    return format_computer_details_enriched(payload, {})


class TestSizes:
    def test_megabytes_become_the_unit_a_person_says(self):
        assert _fmt_mb(512) == "512 MB"
        assert _fmt_mb(16384) == "16 GB"
        assert _fmt_mb(1_048_576) == "1 TB"

    def test_missing_size_is_never_rendered_as_zero(self):
        """"0 GB" reads as a measured value; the dash reads as absent."""
        assert _fmt_mb(0) == "—"
        assert _fmt_mb(None) == "—"
        assert _fmt_mb("nao numerico") == "—"


class TestBlankValues:
    def test_the_string_bracket_pair_counts_as_empty(self):
        """GLPI returns "[]" as a STRING for an asset with no group."""
        assert _is_blank("[]") is True
        assert _blank_to_dash("[]") == "—"

    def test_empty_collections_count_as_empty(self):
        assert _is_blank([]) and _is_blank({}) and _is_blank(())

    def test_a_real_value_survives(self):
        assert not _is_blank("DDR4")
        assert _blank_to_dash("DDR4") == "DDR4"


class TestHardwareSection:
    def test_processor_shows_the_model_not_the_device_id(self):
        out = _render(
            processors=[
                {
                    "deviceprocessors_id": "Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz",
                    "frequency": 3200,
                    "nbcores": 6,
                    "nbthreads": 2,
                }
            ]
        )
        assert "i7-8700" in out
        assert "6 nucleo(s)" in out

    def test_memory_reports_type_and_form_factor(self):
        """DDR4 vs DDR3 and DIMM vs SODIMM decide which part to order."""
        out = _render(
            memories=[
                {"devicememories_id": "DDR4 - 2666 - DIMM", "size": 16384, "busID": "1"}
            ]
        )
        assert "DDR4" in out and "DIMM" in out
        assert "16 GB" in out
        assert "slot 1" in out

    def test_memory_total_sums_every_module(self):
        out = _render(
            memories=[
                {"devicememories_id": "DDR4 - 2666 - SODIMM", "size": 8192},
                {"devicememories_id": "DDR4 - 2666 - SODIMM", "size": 8192},
            ]
        )
        assert "16 GB em 2 modulo(s)" in out

    def test_disk_type_is_never_guessed_from_the_model_name(self):
        """The reference instance records no rpm/type; inferring "SSD" from a
        model string would be a guess wearing the costume of a field."""
        out = _render(
            drives=[
                {"deviceharddrives_id": "KINGSTON SUV400S37240G", "capacity": 240057}
            ]
        )
        assert "KINGSTON SUV400S37240G" in out
        assert "SSD" not in out.replace("KINGSTON SUV400S37240G", "")

    def test_declared_interface_is_shown_when_glpi_has_it(self):
        out = _render(
            drives=[
                {
                    "deviceharddrives_id": "Samsung 980",
                    "capacity": 500000,
                    "interfacetypes_id": "NVMe",
                }
            ]
        )
        assert "NVMe" in out


class TestStorageSection:
    def test_free_space_and_usage_are_reported(self):
        """"Nao consigo salvar" is answered by this row, not by the total."""
        out = _render(
            disks=[
                {
                    "mountpoint": "C:",
                    "filesystems_id": "NTFS",
                    "totalsize": 100000,
                    "freesize": 25000,
                }
            ]
        )
        assert "75%" in out
        assert "C:" in out

    def test_a_nearly_full_volume_is_flagged(self):
        out = _render(
            disks=[{"mountpoint": "C:", "totalsize": 100000, "freesize": 5000}]
        )
        assert "95%" in out and "⚠️" in out

    def test_zero_sized_volumes_are_dropped(self):
        """A recovery partition GLPI reports as 0 tells a technician nothing."""
        out = _render(
            disks=[
                {"mountpoint": "C:", "totalsize": 100000, "freesize": 50000},
                {"mountpoint": "F:", "totalsize": 0, "freesize": 0},
            ]
        )
        assert "C:" in out and "| F: |" not in out


class TestSecuritySection:
    def test_out_of_date_antivirus_is_flagged(self):
        out = _render(
            antivirus=[
                {
                    "name": "Windows Defender",
                    "antivirus_version": "4.18",
                    "signature_version": "1.457",
                    "is_active": 1,
                    "is_uptodate": 0,
                }
            ]
        )
        assert "⚠️" in out

    def test_current_antivirus_is_not_flagged(self):
        out = _render(
            antivirus=[
                {"name": "Windows Defender", "is_active": 1, "is_uptodate": 1}
            ]
        )
        assert "Windows Defender" in out
        assert "⚠️" not in out


class TestSoftwareSection:
    def test_the_program_name_is_the_point_of_the_list(self):
        out = _render(
            software=[
                {"softwares_id": "Microsoft Edge", "softwareversions_id": "120.0"}
            ]
        )
        assert "Microsoft Edge" in out

    def test_the_listing_says_when_it_is_truncated(self):
        out = _render(
            software=[
                {"softwares_id": f"App {i}", "softwareversions_id": "1.0"}
                for i in range(40)
            ]
        )
        assert "exibindo 25 de 40" in out


class TestEmptySections:
    def test_absent_hardware_produces_no_empty_table(self):
        """A heading over nothing reads as "this machine has none"."""
        out = _render()
        for heading in ("## Hardware", "## Armazenamento", "## Seguranca"):
            assert heading not in out


class TestLinkParsing:
    def test_the_related_id_comes_from_the_links_array(self):
        item = {
            "links": [
                {"rel": "Computer", "href": "https://x/api.php/v1/Computer/3"},
                {"rel": "SoftwareVersion", "href": "https://x/api.php/v1/SoftwareVersion/107751"},
            ]
        }
        assert _subitem_link_id(item, "SoftwareVersion") == "107751"

    def test_a_missing_relation_is_none(self):
        assert _subitem_link_id({"links": []}, "SoftwareVersion") is None


class TestTicketLinkedEquipment:
    """18.580 links across 9.292 tickets, none of them surfaced before."""

    def test_the_asset_a_ticket_is_about_is_named(self):
        from src.formatters.glpi_formatters import _linked_items

        out = _linked_items([{"itemtype": "Printer", "name": "SATO WS408 - 17"}])
        assert "Impressora" in out and "SATO WS408 - 17" in out

    def test_the_form_that_opened_the_ticket_is_not_equipment(self):
        """GLPI links the Formcreator form through the same relation."""
        from src.formatters.glpi_formatters import _linked_items

        out = _linked_items(
            [
                {"itemtype": "Printer", "name": "SATO WS408 - 17"},
                {"itemtype": "Glpi\\Form\\Form", "name": "Impressora"},
            ]
        )
        assert "SATO WS408 - 17" in out
        assert "Form" not in out

    def test_several_assets_are_all_listed(self):
        from src.formatters.glpi_formatters import _linked_items

        out = _linked_items(
            [
                {"itemtype": "Computer", "name": "WS019"},
                {"itemtype": "Monitor", "name": "DELL P2317H"},
            ]
        )
        assert "WS019" in out and "DELL P2317H" in out

    def test_no_link_renders_as_absent_not_as_empty(self):
        from src.formatters.glpi_formatters import _linked_items

        assert _linked_items([]) == "—"
        assert _linked_items(None) == "—"

    def test_only_form_objects_reads_as_no_equipment(self):
        from src.formatters.glpi_formatters import _linked_items

        assert _linked_items([{"itemtype": "Glpi\\Form\\Form", "name": "X"}]) == "—"
