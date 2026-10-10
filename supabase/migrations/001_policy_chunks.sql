-- RideWise Assist: policy chunk store (pgvector + full-text, fused with RRF).
-- Run this in the Supabase SQL Editor (or psql) before ingesting.

create extension if not exists vector;

create table if not exists policy_chunks (
  id             text primary key,            -- doc:version:page:idx (idempotent re-ingest)
  doc_id         text not null,
  title          text not null,
  version        text,
  effective_date text,
  page           int not null,
  section        text,
  content        text not null,               -- embedding + FTS text
  display_text   text not null,               -- markdown for the composer
  source_type    text not null default 'pdf',
  embedding      vector(768) not null,
  fts            tsvector generated always as (to_tsvector('english', content)) stored
);

create index if not exists policy_chunks_fts_idx on policy_chunks using gin (fts);
create index if not exists policy_chunks_doc_version_idx on policy_chunks (doc_id, version);

-- No HNSW index: at <10k rows an exact scan is instant, and ANN combined with a
-- version filter can return fewer than k rows.

alter table policy_chunks enable row level security;   -- no anon policies

-- Hybrid search: dense cosine + keyword, fused with Reciprocal Rank Fusion.
create or replace function match_policy_chunks(
  query_embedding vector(768),
  query_text      text,
  p_doc_id        text default null,
  p_version       text default null,
  match_count     int  default 5
)
returns table (
  id text, doc_id text, title text, version text, effective_date text,
  page int, section text, content text, display_text text, source_type text,
  rrf_score double precision, cosine double precision
)
language sql stable
as $$
  with semantic as (
    select c.id,
           row_number() over (order by c.embedding <=> query_embedding) as rank_s,
           1 - (c.embedding <=> query_embedding) as cosine
    from policy_chunks c
    where (p_doc_id  is null or c.doc_id  = p_doc_id)
      and (p_version is null or c.version = p_version)
    order by c.embedding <=> query_embedding
    limit match_count * 4
  ),
  keyword as (
    select c.id,
           row_number() over (
             order by ts_rank_cd(c.fts, websearch_to_tsquery('english', query_text)) desc
           ) as rank_k
    from policy_chunks c
    where (p_doc_id  is null or c.doc_id  = p_doc_id)
      and (p_version is null or c.version = p_version)
      and c.fts @@ websearch_to_tsquery('english', query_text)
    limit match_count * 4
  ),
  fused as (
    select coalesce(s.id, k.id) as id,
           coalesce(1.0 / (60 + s.rank_s), 0.0) + coalesce(1.0 / (60 + k.rank_k), 0.0) as rrf_score,
           coalesce(s.cosine, 0.0) as cosine
    from semantic s
    full outer join keyword k on s.id = k.id
  )
  select c.id, c.doc_id, c.title, c.version, c.effective_date, c.page, c.section,
         c.content, c.display_text, c.source_type, f.rrf_score, f.cosine
  from fused f
  join policy_chunks c on c.id = f.id
  order by f.rrf_score desc
  limit match_count;
$$;
