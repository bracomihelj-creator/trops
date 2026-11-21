from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from trops_studio.config import POWERSHELL_32
from trops_studio.money import ProjestError

POWERSHELL_BRIDGE = r'''
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Open-Ace([string]$path, [string]$extended = "", [bool]$readOnly = $true) {
    $connection = New-Object -ComObject ADODB.Connection
    $connection.ConnectionTimeout = 20
    $extra = if ($extended) { ";Extended Properties=`"$extended`"" } else { "" }
    $mode = if ($readOnly) { ";Mode=Read" } else { "" }
    $connection.Open("Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$path$extra$mode")
    return $connection
}

function Convert-OutValue($value) {
    if ($null -eq $value -or $value -is [DBNull]) { return $null }
    if ($value -is [DateTime]) { return $value.ToString("yyyy-MM-dd") }
    return $value
}

function Read-Rows($connection, [string]$sql, [int]$limit = 200000) {
    $recordset = New-Object -ComObject ADODB.Recordset
    $recordset.Open($sql, $connection, 0, 1)
    $rows = New-Object System.Collections.ArrayList
    $seen = 0
    while (-not $recordset.EOF -and $seen -lt $limit) {
        $row = [ordered]@{}
        for ($i = 0; $i -lt $recordset.Fields.Count; $i++) {
            $field = $recordset.Fields.Item($i)
            $row[[string]$field.Name] = Convert-OutValue $field.Value
        }
        [void]$rows.Add([pscustomobject]$row)
        $recordset.MoveNext()
        $seen++
    }
    $recordset.Close()
    return @($rows)
}

function Try-Rows($connection, [string]$sql) {
    try { return @(Read-Rows $connection $sql) } catch { return @() }
}

function Read-Excel([string]$path, [string]$kind) {
    $excelMode = if ([IO.Path]::GetExtension($path).ToLowerInvariant() -eq ".xls") { "Excel 8.0" } else { "Excel 12.0 Xml" }
    $connection = Open-Ace $path "$excelMode;HDR=YES;IMEX=1;ReadOnly=True" $true
    $schemaRows = @()
    $rs = $connection.OpenSchema(20)
    while (-not $rs.EOF) {
        if ([string]$rs.Fields.Item("TABLE_TYPE").Value -eq "TABLE") {
            $schemaRows += [pscustomobject]@{ TABLE_NAME = [string]$rs.Fields.Item("TABLE_NAME").Value }
        }
        $rs.MoveNext()
    }
    $rs.Close()
    try {
        $sheet = @($schemaRows | Where-Object { $_.TABLE_NAME -match '\$$' } | Select-Object -First 1).TABLE_NAME
        if (-not $sheet) {
            $rs = $connection.OpenSchema(20)
            while (-not $rs.EOF -and -not $sheet) {
                $name = [string]$rs.Fields.Item("TABLE_NAME").Value
                if ($name -match '\$$') { $sheet = $name }
                $rs.MoveNext()
            }
            $rs.Close()
        }
        if (-not $sheet) { throw "Excel datoteka nima lista, ki ga ACE prepozna." }
        $safeSheet = $sheet.Replace("]", "]]" )
        $recordset = New-Object -ComObject ADODB.Recordset
        $recordset.Open("SELECT * FROM [$safeSheet]", $connection, 0, 1)
        $rows = New-Object System.Collections.ArrayList
        while (-not $recordset.EOF) {
            $first = $recordset.Fields.Item(0).Value
            $firstText = if ($null -eq $first -or $first -is [DBNull]) { "" } else { "$first".Trim() }
            if ($firstText -match '^\d+(?:[\.,]\d+)?$' -and [double]($firstText.Replace(",", ".")) -gt 0) {
                $row = [ordered]@{}
                for ($i = 0; $i -lt $recordset.Fields.Count; $i++) {
                    $field = $recordset.Fields.Item($i)
                    $row[[string]$field.Name] = Convert-OutValue $field.Value
                }
                [void]$rows.Add([pscustomobject]$row)
            }
            $recordset.MoveNext()
        }
        $recordset.Close()
        return [pscustomobject]@{ kind = $kind; path = $path; sheet = $sheet; rows = @($rows) }
    } finally {
        $connection.Close()
    }
}

try {
    $requestText = [IO.File]::ReadAllText($env:PROJEST_REQUEST, (New-Object Text.UTF8Encoding($false)))
    $request = $requestText | ConvertFrom-Json
    if ($request.action -eq "excel") {
        $books = New-Object System.Collections.ArrayList
        foreach ($file in @($request.files)) { [void]$books.Add((Read-Excel $file.path $file.kind)) }
        $result = [ordered]@{ ok = $true; books = @($books) }
    } elseif ($request.action -eq "account_history") {
        $connection = Open-Ace $request.database "" $true
        try {
            $recent = Try-Rows $connection "SELECT TOP 5000 [DS],[6-Dobavitelj],[Odhodek01],[Odhodek07],[Plačilo],[3-Dat pre] FROM [tblDDV_KnjigaPR_21] WHERE [3-Dat pre] Is Not Null ORDER BY [3-Dat pre] DESC"
            $rules = Try-Rows $connection "SELECT * FROM [tblPR_KontoPravila] WHERE [Aktivno]=True ORDER BY [Zaporedje]"
            $result = [ordered]@{ ok=$true; recent=@($recent); rules=@($rules) }
        } finally { $connection.Close() }
    } else {
        throw "Neznana operacija: $($request.action)"
    }
    $result | ConvertTo-Json -Depth 12 -Compress
} catch {
    ([ordered]@{ ok=$false; error=$_.Exception.Message; detail="$($_.InvocationInfo.PositionMessage)" } | ConvertTo-Json -Depth 5 -Compress)
    exit 1
}
'''


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Nepodprt JSON tip: {type(value).__name__}")


def run_bridge(request: Mapping[str, Any], *, timeout: int = 180) -> dict[str, Any]:
    if os.name != "nt":
        raise ProjestError("Excel/ACE most je podprt samo v Windows okolju.")
    if not POWERSHELL_32.is_file():
        raise ProjestError(f"32-bitni PowerShell ni najden: {POWERSHELL_32}")
    payload_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as stream:
            json.dump(request, stream, ensure_ascii=False, default=_json_value)
            payload_path = Path(stream.name)
        encoded = base64.b64encode(POWERSHELL_BRIDGE.encode("utf-16le")).decode("ascii")
        env = os.environ.copy()
        env["PROJEST_REQUEST"] = str(payload_path)
        process = subprocess.run(
            [
                str(POWERSHELL_32),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout = process.stdout.strip().lstrip("\ufeff")
        try:
            result = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError as exc:
            detail = (process.stderr or stdout or "brez izpisa").strip()
            raise ProjestError(f"ACE most je vrnil neveljaven odgovor: {detail[:1000]}") from exc
        if process.returncode != 0 or not result.get("ok"):
            message = result.get("error") or (process.stderr or "").strip() or "neznana napaka ACE mostu"
            raise ProjestError(str(message))
        return result
    except subprocess.TimeoutExpired as exc:
        raise ProjestError("Branje Excela/Accessa je trajalo predolgo.") from exc
    finally:
        if payload_path:
            try:
                payload_path.unlink(missing_ok=True)
            except OSError:
                pass


def read_excel_books(files: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    result = run_bridge(
        {
            "action": "excel",
            "files": [{"kind": kind, "path": str(path)} for kind, path in files],
        }
    )
    books = result.get("books")
    if books is None:
        return []
    return books if isinstance(books, list) else [books]


def read_account_history(database: Path) -> dict[str, Any]:
    return run_bridge({"action": "account_history", "database": str(database)})
