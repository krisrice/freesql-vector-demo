# Building a Hands-On Oracle 26ai Vector Search App on FreeSQL.com

Vector search is much easier to understand when you can see the whole flow end to end: create a table, generate embeddings, store vectors, run similarity search, and inspect what the database is actually comparing.

That is the goal of this small project:

**FreeSQL Vector Demo**  
`https://github.com/krisrice/freesql-vector-demo`

It is a hands-on learning app for Oracle Database 26ai vector search on FreeSQL.com. The demo uses automotive parts inventory as the sample domain, but the pattern applies to any app where users search by meaning instead of exact keywords.

A user can type something like:

```text
2019 F-150 misfire rough idle coil
```

and find ignition-related parts even if the exact search phrase is not stored in the table. That is the practical value of vector search: the query and the stored rows are compared by semantic similarity.

## What the Demo Does

The app is intentionally small and direct. It is one Python process that serves both a REST API and a lightweight React UI.

It does a few core things:

- creates an Oracle table with a native `VECTOR(384, int8)` column
- generates at least 1,000 realistic automotive parts rows
- uses `all-MiniLM-L6-v2` to generate local embeddings
- stores those embeddings in Oracle Database 26ai
- searches with `vector_distance`
- shows the query vector, row vectors, and cosine distance scores in a Details tab

The table looks like a normal application table, with one important addition:

```sql
embedding vector(384, int8) not null
```

The search pattern is also straightforward:

```sql
select *
from (
    select
        id,
        part_number,
        name,
        category,
        description,
        unit_price,
        vector_distance(embedding, :query_vector, cosine) as distance
    from automotive_parts
    order by distance
)
where rownum <= :result_limit
```

Lower cosine distance means the row is closer to the meaning of the search query.

## Why FreeSQL.com Matters Here

This demo is possible because FreeSQL.com now supports **TCPS connections for the Python thin driver**.

That is a big usability improvement.

With the Python thin driver, you do not need to install Oracle Client libraries locally. The app can connect using `oracledb` in thin mode, with a TCPS DSN like this:

```bash
ORACLE_DSN="(description=(address=(protocol=tcps)(port=2484)(host=db.freesql.com))(connect_data=(service_name=26ai_un3c1)))"
```

That keeps the setup simple:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py --host 127.0.0.1 --port 8088
```

From there, the browser app can install the table, generate embeddings, insert rows, and run vector searches.

For a learning project, that matters. The fewer setup steps there are, the faster someone can get to the actual point: understanding how Oracle vector search works.

## The Browser App Is Part of the Teaching

The app has three tabs.

**Search** is the normal user experience. Type a natural language query and get matching parts back.

**Install/Reinstall** lets the user create or reset the demo data from the browser. It also shows separate progress for embedding generation and row inserts. That distinction is useful because vectorization can take time, especially on the first run when the model is downloaded.

**Details** is where the app becomes more educational. It shows the generated query vector, the returned row vectors, and the similarity scores. This makes the relationship between the UI, the model, and the SQL visible.

That is important because vector search can otherwise feel like magic. It is not magic. It is a query vector being compared against stored row vectors using a distance function.

## Why Use `int8` Vectors?

The demo stores embeddings as `VECTOR(384, int8)`.

The embedding model produces floating point values, then the app normalizes and quantizes them into signed 8-bit integers before storing them. That keeps the lab small and practical while still demonstrating the real Oracle vector data type and search flow.

For a teaching app, this is a good tradeoff. It keeps the focus on the database feature and search behavior without making the dataset or storage requirements too heavy.

## What You Can Learn From It

This demo is meant to answer a few practical questions:

- How do I connect Python to Oracle Database 26ai on FreeSQL.com?
- How do I define a table with a `VECTOR` column?
- How do I generate embeddings from application text?
- How do I store vectors in Oracle?
- How do I search with `vector_distance`?
- What does the database compare during semantic search?
- How do query vectors and row vectors relate to the final score?

The automotive parts domain is just a convenient example. The same structure could apply to support tickets, product catalogs, documentation, customer records, maintenance logs, or any dataset where meaning matters more than exact text matching.

## Try It

The repo is here:

`https://github.com/krisrice/freesql-vector-demo`

Create a `.env` file from `.env.example`, add your FreeSQL username and password, then run the app.

The first install will generate embeddings for the sample data and insert them into Oracle Database 26ai. After that, you can search, reset, inspect vectors, and experiment with different queries.

The goal is not just to show that vector search works. The goal is to make it understandable.
