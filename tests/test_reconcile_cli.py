"""Pruebas del uso desde la terminal y del Excel."""

from pathlib import Path

from openpyxl import load_workbook

from reconcile import main

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


def test_cli_prints_summary_and_writes_excel(tmp_path, capsys):
    output = tmp_path / "report.xlsx"
    code = main([str(SAMPLES / "bank.csv"), str(SAMPLES / "invoices.csv"), "--output", str(output)])
    assert code == 0

    printed = capsys.readouterr().out
    assert "Matched:" in printed and "Needs review:" in printed and "Difference:" in printed

    workbook = load_workbook(output)
    assert workbook.sheetnames == ["Summary", "Matched", "Review", "Unmatched bank", "Unmatched invoices"]
    assert workbook["Matched"]["A1"].value == "Status"
    assert workbook["Matched"]["E2"].number_format.startswith('"$"')
    # 9 movimientos del banco sin factura y 5 facturas sin pago (+ encabezado)
    assert workbook["Unmatched bank"].max_row == 10
    assert workbook["Unmatched invoices"].max_row == 6


def test_cli_works_with_debit_credit_bank_file(tmp_path, capsys):
    code = main([str(SAMPLES / "bank_debit_credit.csv"), str(SAMPLES / "invoices.csv"),
                 "--output", str(tmp_path / "r.xlsx")])
    assert code == 0
    assert "Matched:          46" in capsys.readouterr().out


def test_cli_reports_bad_file_without_crashing(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("Something,Else\n1,2\n")
    code = main([str(bad), str(SAMPLES / "invoices.csv"), "--output", str(tmp_path / "r.xlsx")])
    assert code == 1
    assert "date column" in capsys.readouterr().err


def test_cli_missing_file(tmp_path, capsys):
    code = main([str(tmp_path / "nope.csv"), str(SAMPLES / "invoices.csv")])
    assert code == 1
    assert "Error" in capsys.readouterr().err
