-- One row per SatQuery analysis, owned by the user who asked it.
-- Applied to the satquery-ai project on 2026-10-17. Run it in the SQL editor
-- (or `supabase db push`) to set up another project.
--
-- The backend writes rows with the asking user's own access token, so row
-- level security, not the backend, is what keeps one user's history from
-- another's.
create table public.analyses (
  id text primary key check (id ~ '^task_[0-9a-f]{12}$'),
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  query text not null check (char_length(query) <= 2000),
  status text not null,
  outcome text not null,
  answer text not null,
  tool text,
  -- The full TaskResponse, so a result can be shown again after the analysis
  -- service restarts.
  response jsonb not null,
  created_at timestamptz not null default now()
);

create index analyses_user_created_idx on public.analyses (user_id, created_at desc);

alter table public.analyses enable row level security;

create policy "Users read their own analyses"
  on public.analyses for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "Users record their own analyses"
  on public.analyses for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "Users delete their own analyses"
  on public.analyses for delete to authenticated
  using ((select auth.uid()) = user_id);

revoke all on public.analyses from anon;
grant select, insert, delete on public.analyses to authenticated;
