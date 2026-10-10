"""Live schema introspection via PRAGMA. Captured BEFORE the DB is locked."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class Column:
    name: str
    type: str
    pk: bool = False
    notnull: bool = False


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    foreign_keys: list[tuple[str, str, str]] = field(default_factory=list)  # (col, ref_table, ref_col)

    @property
    def pk(self) -> str | None:
        for c in self.columns:
            if c.pk:
                return c.name
        return None


@dataclass
class SchemaInfo:
    tables: dict[str, Table] = field(default_factory=dict)

    def has_table(self, name: str) -> bool:
        return name in self.tables

    def has_column(self, table: str, col: str) -> bool:
        t = self.tables.get(table)
        return bool(t and any(c.name == col for c in t.columns))

    def render(self) -> str:
        """Compact schema text for prompts."""
        lines = []
        for t in self.tables.values():
            cols = ", ".join(
                f"{c.name} {c.type}" + (" PK" if c.pk else "") for c in t.columns)
            lines.append(f"{t.name}({cols})")
            for col, rt, rc in t.foreign_keys:
                lines.append(f"   FK {t.name}.{col} -> {rt}.{rc}")
        return "\n".join(lines)


def introspect(conn: sqlite3.Connection) -> SchemaInfo:
    info = SchemaInfo()
    names = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table' "
        "and name not like 'sqlite_%' order by name").fetchall()]
    for name in names:
        t = Table(name=name)
        for cid, cname, ctype, notnull, dflt, pk in conn.execute(
                f'PRAGMA table_info("{name}")').fetchall():
            t.columns.append(Column(cname, ctype or "", bool(pk), bool(notnull)))
        for row in conn.execute(f'PRAGMA foreign_key_list("{name}")').fetchall():
            # row: (id, seq, table, from, to, on_update, on_delete, match)
            t.foreign_keys.append((row[3], row[2], row[4]))
        info.tables[name] = t
    return info
