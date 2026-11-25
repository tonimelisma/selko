"""Import Selko's Postgres (Supabase) database and its attachment files.

Run once at cutover, on the server, from the importer image
``ghcr.io/tonimelisma/selko-import:<sha>`` (docs/specs/sqlite-single-process/
04-data-cutover.md §A-B; ``python -m selko_import --help``):

    database     --source-url-file F --target <data dir>/selko.db
    attachments  --source-url-file F --storage-url URL --storage-key-file F --data-dir <data dir>

It lives outside ``selko`` because it needs a Postgres driver, which ``selko``
must never import; it is deleted after the cutover.

How a value travels: Postgres renders every cell as text with the expression
for its type (`CONVERT`), the importer stores that text (as INTEGER or REAL
where the SQLite column is), and both sides then hash every row with the same
length-prefixed encoding. A difference in any cell of any row changes the
table's (count, sum, xor) triple. Triggers are dropped during the load (they
would rewrite the copied values) and recreated after. Nothing about row
contents is ever printed: progress shows table names and counts only.
"""
